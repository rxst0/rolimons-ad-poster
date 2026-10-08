"""Startup checks shared by the CLI and GUI: cookie, config, item validation, value report."""
import logging
import random
import threading
from pathlib import Path

import requests

from .config import Config, ConfigError, load_config, validate_config
from .cookie import COOKIE_ENV_VAR, get_cookie, load_env_file
from .items import ItemCatalog, fetch_catalog
from .logsetup import REDACTOR
from .paths import env_path
from .values import evaluate_ad, value_warnings

log = logging.getLogger("roliposter.startup")


class StartupError(Exception):
    pass


def load_cookie() -> str:
    load_env_file(env_path())
    try:
        cookie = get_cookie()
    except ValueError as e:
        raise StartupError(str(e)) from None
    if not cookie:
        raise StartupError(
            f"No Rolimons cookie found. Set {COOKIE_ENV_VAR} in the environment or in {env_path()} "
            "(see .env.example)."
        )
    REDACTOR.add_secret(cookie)
    return cookie


def load_valid_config(path: Path) -> Config:
    try:
        cfg = load_config(path)
    except ConfigError as e:
        raise StartupError(str(e)) from None
    errors = validate_config(cfg)
    if errors:
        raise StartupError("config.json problems:\n  - " + "\n  - ".join(errors))
    return cfg


def fetch_catalog_with_retry(session: requests.Session, stop_event: threading.Event | None = None,
                             attempts: int = 4) -> ItemCatalog:
    stop_event = stop_event or threading.Event()
    delay = 5.0
    for attempt in range(1, attempts + 1):
        try:
            catalog = fetch_catalog(session)
            log.info("Loaded %d items from Rolimons itemdetails.", len(catalog))
            return catalog
        except (requests.RequestException, ValueError) as e:
            log.warning("Item catalog fetch failed (attempt %d/%d): %s", attempt, attempts, type(e).__name__)
            if attempt == attempts or stop_event.wait(delay * random.uniform(0.8, 1.2)):
                break
            delay *= 2
    raise StartupError("Could not download the Rolimons item list; check your connection and try again.")


def missing_items(cfg: Config, catalog: ItemCatalog) -> dict[str, list[int]]:
    missing = {}
    for ad in cfg.ads:
        bad = [i for i in ad.all_item_ids() if catalog.get(i) is None]
        if bad:
            missing[ad.name] = bad
    return missing


def _describe_items(ids: list[int], catalog: ItemCatalog) -> list[str]:
    lines = []
    for item_id in ids:
        item = catalog.get(item_id)
        if item is None:
            lines.append(f"{item_id}  <-- NOT FOUND on Rolimons")
            continue
        value = f"{item.value:,}" if item.value >= 0 else f"no value (RAP {item.rap:,})"
        flags = [f for f, on in (("PROJECTED", item.projected), ("rare", item.rare), ("hyped", item.hyped)) if on]
        extra = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"{item_id}  {item.label} | value {value} | demand {item.demand_label}{extra}")
    return lines


def report_ads(cfg: Config, catalog: ItemCatalog) -> list[str]:
    """Logs every ad with resolved item names and values; returns value warnings."""
    warnings = []
    for ad in cfg.ads:
        state = "" if ad.enabled else " (disabled)"
        log.info("Ad '%s'%s", ad.name, state)
        for line in _describe_items(ad.offer_item_ids, catalog):
            log.info("    offer   : %s", line)
        for line in _describe_items(ad.request_item_ids, catalog):
            log.info("    request : %s", line)
        if ad.request_tags:
            log.info("    tags    : %s", ", ".join(ad.request_tags))
        av = evaluate_ad(ad, catalog)
        if av.request_value is not None:
            log.info("    value   : offer %s vs request %s (%+.0f%%)",
                     f"{av.offer_value:,}", f"{av.request_value:,}", av.overpay_percent or 0)
        else:
            log.info("    value   : offer %s (request is tags only)", f"{av.offer_value:,}")
        if cfg.value_mode.enabled and ad.enabled:
            warnings.extend(value_warnings(ad, av, cfg.value_mode))
    for w in warnings:
        log.warning("VALUE WARNING: %s", w)
    return warnings


def prepare(config_path: Path, session: requests.Session,
            stop_event: threading.Event | None = None) -> tuple[Config, str, ItemCatalog]:
    cookie = load_cookie()
    cfg = load_valid_config(config_path)
    log.info("Config OK: %d ad(s), %d enabled, rotation=%s, user ID %d.",
             len(cfg.ads), len(cfg.enabled_ads()), cfg.rotation, cfg.roblox_user_id)
    catalog = fetch_catalog_with_retry(session, stop_event)
    report_ads(cfg, catalog)
    missing = missing_items(cfg, catalog)
    if missing:
        detail = "; ".join(f"'{name}': {ids}" for name, ids in missing.items())
        raise StartupError(f"Unknown item IDs (not limiteds on Rolimons): {detail}")
    return cfg, cookie, catalog
