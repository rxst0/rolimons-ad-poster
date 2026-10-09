"""The posting loop: rotation, cooldown + jitter, retries/backoff, hot config reload."""
import logging
import random
import threading
import time
from pathlib import Path

import requests

from .api import Outcome, PostResult, RolimonsClient
from .config import Ad, Config, ConfigError, load_config, validate_config
from .inventory import Inventory, fetch_inventory, missing_offer_items
from .items import ItemCatalog, fetch_catalog
from .paths import state_path
from .schedule import seconds_until_allowed
from .state import PostHistory
from .values import evaluate_ad, is_overpaying, pick_weight

log = logging.getLogger("roliposter.poster")

BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 15 * 60
COOLDOWN_RETRY_SECONDS = (60.0, 120.0)
MAX_COOLDOWN_RETRIES = 20
REJECT_PAUSE_SECONDS = 30.0
NOTHING_POSTABLE_RECHECK_SECONDS = 10 * 60
CATALOG_REFRESH_SECONDS = 30 * 60
INVENTORY_REFRESH_SECONDS = 5 * 60


class AuthError(RuntimeError):
    """The Rolimons verification cookie is missing, invalid or expired."""


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


class Poster:
    def __init__(self, cfg: Config, config_path: Path, cookie: str, catalog: ItemCatalog,
                 stop_event: threading.Event | None = None, session: requests.Session | None = None):
        self.cfg = cfg
        self.config_path = config_path
        self.catalog = catalog
        self.stop_event = stop_event or threading.Event()
        self.session = session or requests.Session()
        self.client = RolimonsClient(self.session, cookie, cfg.roblox_user_id)
        self.history = PostHistory(state_path())
        self.inventory: Inventory | None = None
        self.unavailable: dict[str, list[int]] = {}  # ad name -> offered item IDs you don't own
        self._config_mtime = self._mtime()
        self._seq_index = 0
        self._last_ad_name: str | None = None
        self._lock = threading.Lock()
        self._seen_raw: set[Outcome] = set()
        # Read by the GUI for its status line / countdown / next-ad preview.
        self.status_text = "Starting"
        self.wait_until: float | None = None
        self.next_ad: Ad | None = None

    # ---- control -------------------------------------------------------
    @property
    def stopped(self) -> bool:
        return self.stop_event.is_set()

    def stop(self) -> None:
        self.stop_event.set()

    def sleep(self, seconds: float, reason: str) -> bool:
        """Interruptible sleep in 1s slices (keeps Ctrl+C / Stop responsive). False if stopped."""
        if seconds > 0:
            log.info("Waiting %s (%s).", fmt_duration(seconds), reason)
            self.status_text, self.wait_until = reason, time.time() + seconds
            deadline = time.monotonic() + seconds
            while not self.stopped:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.stop_event.wait(min(1.0, remaining))
            self.wait_until = None
        return not self.stopped

    def skip_next(self) -> Ad | None:
        """Replaces the planned next ad with the one after it. Safe to call from another thread."""
        with self._lock:
            if self.next_ad is not None:
                self._last_ad_name = self.next_ad.name
                self.next_ad = self._choose_ad(refresh=False)
                log.info("Skipped ahead; next ad will be '%s'.", self.next_ad.name if self.next_ad else "none")
            return self.next_ad

    # ---- main loop -----------------------------------------------------
    def run(self) -> None:
        log.info("Poster started: %d enabled ad(s), rotation=%s, value mode=%s.",
                 len(self.cfg.enabled_ads()), self.cfg.rotation,
                 self.cfg.value_mode.strategy if self.cfg.value_mode.enabled else "off")
        consecutive_failures = 0
        try:
            if not self._wait_initial_cooldown():
                return
            while not self.stopped:
                self._maybe_reload_config()
                self._maybe_refresh_catalog()
                if not self._wait_for_posting_hours():
                    return
                ad = self._take_next_ad()
                if ad is None:
                    if not self.cfg.enabled_ads():
                        log.error("No enabled ads. Stopping.")
                        return
                    if not self.sleep(NOTHING_POSTABLE_RECHECK_SECONDS, "every enabled ad is being skipped"):
                        return
                    continue
                if not self._wait_for_quota():
                    return
                result = self._post_with_retries(ad)
                if result is None:
                    return
                if result.outcome is Outcome.SUCCESS:
                    consecutive_failures = 0
                    self.history.record(ad.name)
                    log.info("Posted %d ad(s) in the last 24h (cap %d).",
                             self.history.count_24h(), self.cfg.max_ads_per_24h)
                    self._plan_next()
                    if not self.sleep(self._cooldown_with_jitter(), "cooldown before next ad"):
                        return
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= max(1, len(self.cfg.enabled_ads())):
                        log.error("Every enabled ad failed in a row; stopping. Check the messages above.")
                        return
                    self._plan_next()
                    if not self.sleep(REJECT_PAUSE_SECONDS, "ad not posted, moving to next ad"):
                        return
        finally:
            self.next_ad = None
            log.info("Poster stopped.")

    def post_once(self) -> bool:
        """Posts a single ad (respecting cooldown/quota/hours). Returns True on success."""
        if not self._wait_initial_cooldown() or not self._wait_for_quota() or not self._wait_for_posting_hours():
            return False
        ad = self._take_next_ad()
        if ad is None:
            log.error("No postable ads.")
            return False
        result = self._post_with_retries(ad)
        if result is not None and result.outcome is Outcome.SUCCESS:
            self.history.record(ad.name)
            return True
        return False

    def _cooldown_with_jitter(self) -> float:
        lo, hi = self.cfg.jitter_seconds
        return self.cfg.cooldown_minutes * 60 + random.uniform(lo, hi)

    def _wait_initial_cooldown(self) -> bool:
        last = self.history.last_post_time()
        if last is None:
            return True
        remaining = self.cfg.cooldown_minutes * 60 - (time.time() - last)
        if remaining <= 0:
            return True
        return self.sleep(remaining + random.uniform(5, 30), "last ad was posted recently")

    def _wait_for_quota(self) -> bool:
        wait = self.history.seconds_until_quota(self.cfg.max_ads_per_24h)
        if wait <= 0:
            return True
        return self.sleep(wait + random.uniform(10, 60), f"reached {self.cfg.max_ads_per_24h} ads in 24h")

    def _wait_for_posting_hours(self) -> bool:
        wait = seconds_until_allowed(self.cfg.posting_hours)
        if wait <= 0:
            return True
        hours = self.cfg.posting_hours
        return self.sleep(wait + random.uniform(10, 90), f"outside posting hours ({hours.start}-{hours.end})")

    def _backoff(self, failures: int) -> float:
        return min(BACKOFF_BASE_SECONDS * 2 ** (failures - 1), BACKOFF_MAX_SECONDS) * random.uniform(0.8, 1.2)

    def _log_attempt(self, ad: Ad, result: PostResult) -> None:
        level = logging.INFO if result.outcome is Outcome.SUCCESS else logging.WARNING
        http = result.status_code if result.status_code is not None else "-"
        log.log(level, "POST ad='%s' result=%s http=%s msg=%s", ad.name, result.outcome.value, http, result.message)
        # The success and cooldown replies are undocumented; record the first of each verbatim.
        if result.outcome in (Outcome.SUCCESS, Outcome.COOLDOWN) and result.outcome not in self._seen_raw:
            self._seen_raw.add(result.outcome)
            log.info("Rolimons reply (%s): %s", result.outcome.value, result.raw or "<empty>")
        self.history.record_attempt(ad.name, result.outcome.value, result.message)

    def _post_with_retries(self, ad: Ad) -> PostResult | None:
        """Posts one ad, retrying through cooldown/network/server errors. None if stopped."""
        failures = 0
        cooldown_hits = 0
        while not self.stopped:
            self.status_text = f"Posting '{ad.name}'"
            result = self.client.post_ad(ad)
            self._log_attempt(ad, result)
            outcome = result.outcome
            if outcome in (Outcome.SUCCESS, Outcome.REJECTED):
                return result
            if outcome is Outcome.AUTH_ERROR:
                raise AuthError(result.message)
            if outcome is Outcome.COOLDOWN:
                cooldown_hits += 1
                if cooldown_hits > MAX_COOLDOWN_RETRIES:
                    log.error("Ad '%s' still on cooldown after %d retries; skipping it.", ad.name, cooldown_hits - 1)
                    return result
                wait, reason = result.retry_after or random.uniform(*COOLDOWN_RETRY_SECONDS), "still on cooldown"
            elif outcome is Outcome.RATE_LIMITED:
                failures += 1
                wait, reason = result.retry_after or max(60.0, self._backoff(failures)), "rate limited"
            else:
                failures += 1
                wait = result.retry_after or self._backoff(failures)
                reason = f"{outcome.value.lower()} #{failures}, backing off"
            if not self.sleep(wait, reason):
                return None
        return None

    # ---- ad selection --------------------------------------------------
    def _plan_next(self) -> None:
        with self._lock:
            self.next_ad = self._choose_ad()

    def _take_next_ad(self) -> Ad | None:
        """The planned ad (re-read from the current config, in case it was edited), else a fresh pick."""
        with self._lock:
            planned, self.next_ad = self.next_ad, None
            if planned is not None:
                for ad in self._eligible_ads():
                    if ad.name == planned.name:
                        return ad
            return self._choose_ad()

    def _eligible_ads(self, refresh: bool = True) -> list[Ad]:
        ads = self.cfg.enabled_ads()
        vm = self.cfg.value_mode
        if vm.enabled and vm.skip_overpaying_ads:
            kept = [a for a in ads if not is_overpaying(evaluate_ad(a, self.catalog), vm)]
            for a in ads:
                if a not in kept:
                    log.info("Skipping ad '%s' (overpays by more than %g%%).", a.name, vm.overpay_warn_percent)
            ads = kept
        if self.cfg.skip_unowned_items:
            if refresh:
                self._maybe_refresh_inventory()
            unavailable = {a.name: m for a in ads if (m := missing_offer_items(a, self.inventory))}
            for name, missing in unavailable.items():
                if self.unavailable.get(name) != missing:
                    names = ", ".join(self._item_name(i) for i in missing)
                    log.warning("Skipping ad '%s': you don't own %s.", name, names)
            self.unavailable = unavailable
            ads = [a for a in ads if a.name not in unavailable]
        return ads

    def _choose_ad(self, refresh: bool = True) -> Ad | None:
        ads = self._eligible_ads(refresh)
        if not ads:
            return None
        vm = self.cfg.value_mode
        if vm.enabled and vm.strategy == "pick":
            pool = self._without_last(ads)
            weights = [pick_weight(evaluate_ad(a, self.catalog)) for a in pool]
            ad = random.choices(pool, weights=weights, k=1)[0]
        elif self.cfg.rotation == "random":
            ad = random.choice(self._without_last(ads))
        else:
            ad = ads[self._seq_index % len(ads)]
            self._seq_index += 1
        self._last_ad_name = ad.name
        return ad

    def _without_last(self, ads: list[Ad]) -> list[Ad]:
        pool = [a for a in ads if a.name != self._last_ad_name]
        return pool or ads

    def _item_name(self, item_id: int) -> str:
        item = self.catalog.get(item_id)
        return item.name if item else str(item_id)

    # ---- live updates --------------------------------------------------
    def _mtime(self) -> float | None:
        try:
            return self.config_path.stat().st_mtime
        except OSError:
            return None

    def _maybe_reload_config(self) -> None:
        mtime = self._mtime()
        if mtime is None or mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        try:
            new_cfg = load_config(self.config_path)
        except ConfigError as e:
            log.warning("config.json changed but could not be loaded (%s); keeping previous config.", e)
            return
        errors = validate_config(new_cfg)
        unknown = [i for ad in new_cfg.ads for i in ad.all_item_ids() if self.catalog.get(i) is None]
        if unknown:
            errors.append(f"unknown item IDs {unknown}")
        if errors:
            log.warning("config.json changed but is invalid (%s); keeping previous config.", "; ".join(errors))
            return
        self.cfg = new_cfg
        self.client.user_id = new_cfg.roblox_user_id
        log.info("Reloaded config.json: %d enabled ad(s).", len(new_cfg.enabled_ads()))

    def _maybe_refresh_catalog(self) -> None:
        if not self.cfg.value_mode.enabled or self.catalog.age_seconds() < CATALOG_REFRESH_SECONDS:
            return
        try:
            self.catalog = fetch_catalog(self.session)
            log.info("Refreshed item values (%d items).", len(self.catalog))
        except (requests.RequestException, ValueError) as e:
            log.warning("Could not refresh item values (%s); using cached values.", type(e).__name__)

    def _maybe_refresh_inventory(self) -> None:
        if self.inventory is not None and self.inventory.age_seconds() < INVENTORY_REFRESH_SECONDS:
            return
        try:
            self.inventory = fetch_inventory(self.session, self.cfg.roblox_user_id)
            if self.inventory.private:
                log.warning("Your Rolimons inventory is private, so owned items can't be checked.")
        except (requests.RequestException, ValueError) as e:
            log.warning("Could not check your inventory (%s); not skipping any ads for it.", type(e).__name__)
            if self.inventory is None:
                self.inventory = Inventory(private=True)  # unknown: don't skip; retry after the refresh interval
