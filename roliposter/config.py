"""config.json loading, saving and validation."""
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

VALID_TAGS = ("any", "demand", "rares", "robux", "upgrade", "downgrade", "rap", "wishlist", "projecteds", "adds")
MAX_OFFER_ITEMS = 4
MAX_REQUEST_SLOTS = 4  # request items + tags share the 4 request slots on Rolimons
MIN_COOLDOWN_MINUTES = 15.0


class ConfigError(Exception):
    pass


@dataclass
class Ad:
    name: str
    offer_item_ids: list[int] = field(default_factory=list)
    request_item_ids: list[int] = field(default_factory=list)
    request_tags: list[str] = field(default_factory=list)
    enabled: bool = True

    def all_item_ids(self) -> list[int]:
        return self.offer_item_ids + self.request_item_ids


@dataclass
class ValueSettings:
    enabled: bool = False
    strategy: str = "warn"  # "warn" = only warn; "pick" = choose ads weighted by offer demand
    overpay_warn_percent: float = 25.0
    skip_overpaying_ads: bool = False


@dataclass
class PostingHours:
    enabled: bool = False
    start: str = "09:00"  # local time, HH:MM; start > end means overnight (e.g. 18:00-02:00)
    end: str = "23:00"


@dataclass
class AutoAcceptSettings:
    """Android, with "Read my trades directly": accept new received trades that pass every rule set here.
    "test" only reports what it would accept. A gain left as None isn't checked."""
    enabled: bool = False
    mode: str = "test"                      # "test" or "live"
    min_value_gain: float | None = 10.0     # % gain in Rolimons value (RAP when an item has no value)
    min_rap_gain: float | None = None       # % gain in RAP
    min_price_gain: float | None = None     # % gain in current best price
    block_projected: bool = True            # never accept when you'd get a projected item
    max_per_day: int = 5                    # live mode: at most this many auto-accepts a day


@dataclass
class AppSettings:
    close_to_tray: bool = True        # keep posting in the tray when the window is closed
    auto_start_posting: bool = False  # start posting as soon as the app opens
    notifications: bool = True
    trade_notifications: bool = True  # Android: "New trade from X" notifications
    # Android: keep an encrypted copy of the Roblox sign-in so trades can be read without the Roblox page
    # (the app's own trades list, and new-trade checks from the background). Off = cookieless.
    direct_trades: bool = False
    check_updates: bool = True
    rovalra: bool = True              # load the bundled RoValra extension in the Received trades tab


@dataclass
class Config:
    roblox_user_id: int = 0
    rotation: str = "sequential"  # or "random"
    cooldown_minutes: float = MIN_COOLDOWN_MINUTES
    jitter_seconds: list[float] = field(default_factory=lambda: [20.0, 120.0])
    max_ads_per_24h: int = 55
    value_mode: ValueSettings = field(default_factory=ValueSettings)
    skip_unowned_items: bool = True
    posting_hours: PostingHours = field(default_factory=PostingHours)
    app: AppSettings = field(default_factory=AppSettings)
    auto_accept: AutoAcceptSettings = field(default_factory=AutoAcceptSettings)
    ads: list[Ad] = field(default_factory=list)

    def enabled_ads(self) -> list[Ad]:
        return [a for a in self.ads if a.enabled]


def _int_list(value, where: str) -> list[int]:
    if not isinstance(value, list):
        raise ConfigError(f"{where} must be a list of item IDs")
    try:
        return [int(v) for v in value]
    except (TypeError, ValueError):
        raise ConfigError(f"{where} contains a non-numeric item ID: {value!r}") from None


def _optional_float(value) -> float | None:
    return None if value is None or value == "" else float(value)


def config_from_dict(data: dict) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("config.json must contain a JSON object")
    try:
        ads = []
        for i, raw in enumerate(data.get("ads", [])):
            where = f"ads[{i}]"
            ads.append(Ad(
                name=str(raw.get("name") or f"Ad {i + 1}").strip(),
                offer_item_ids=_int_list(raw.get("offer_item_ids", []), f"{where}.offer_item_ids"),
                request_item_ids=_int_list(raw.get("request_item_ids", []), f"{where}.request_item_ids"),
                request_tags=[str(t).strip().lower() for t in raw.get("request_tags", [])],
                enabled=bool(raw.get("enabled", True)),
            ))
        vm = data.get("value_mode", {}) or {}
        ph = data.get("posting_hours", {}) or {}
        app = data.get("app", {}) or {}
        aa = data.get("auto_accept", {}) or {}
        return Config(
            roblox_user_id=int(data.get("roblox_user_id", 0) or 0),
            rotation=str(data.get("rotation", "sequential")).lower(),
            cooldown_minutes=float(data.get("cooldown_minutes", MIN_COOLDOWN_MINUTES)),
            jitter_seconds=[float(x) for x in data.get("jitter_seconds", [20, 120])],
            max_ads_per_24h=int(data.get("max_ads_per_24h", 55)),
            value_mode=ValueSettings(
                enabled=bool(vm.get("enabled", False)),
                strategy=str(vm.get("strategy", "warn")).lower(),
                overpay_warn_percent=float(vm.get("overpay_warn_percent", 25.0)),
                skip_overpaying_ads=bool(vm.get("skip_overpaying_ads", False)),
            ),
            skip_unowned_items=bool(data.get("skip_unowned_items", True)),
            posting_hours=PostingHours(
                enabled=bool(ph.get("enabled", False)),
                start=str(ph.get("start", "09:00")),
                end=str(ph.get("end", "23:00")),
            ),
            app=AppSettings(
                close_to_tray=bool(app.get("close_to_tray", True)),
                auto_start_posting=bool(app.get("auto_start_posting", False)),
                notifications=bool(app.get("notifications", True)),
                trade_notifications=bool(app.get("trade_notifications", True)),
                direct_trades=bool(app.get("direct_trades", False)),
                check_updates=bool(app.get("check_updates", True)),
                rovalra=bool(app.get("rovalra", True)),
            ),
            auto_accept=AutoAcceptSettings(
                enabled=bool(aa.get("enabled", False)),
                mode=str(aa.get("mode", "test")).lower(),
                min_value_gain=_optional_float(aa.get("min_value_gain", 10.0)),
                min_rap_gain=_optional_float(aa.get("min_rap_gain")),
                min_price_gain=_optional_float(aa.get("min_price_gain")),
                block_projected=bool(aa.get("block_projected", True)),
                max_per_day=int(aa.get("max_per_day", 5)),
            ),
            ads=ads,
        )
    except (TypeError, ValueError, AttributeError) as e:
        raise ConfigError(f"Malformed config: {e}") from None


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path} (copy config.example.json to config.json)")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path.name} is not valid JSON: line {e.lineno}, col {e.colno}: {e.msg}") from None
    return config_from_dict(data)


def save_config(cfg: Config, path: Path) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def validate_config(cfg: Config) -> list[str]:
    """Returns a list of human-readable problems (empty = OK). Item existence is checked separately."""
    errors = []
    if cfg.roblox_user_id <= 0:
        errors.append("roblox_user_id must be your numeric Roblox user ID.")
    if cfg.rotation not in ("sequential", "random"):
        errors.append('rotation must be "sequential" or "random".')
    if cfg.cooldown_minutes < MIN_COOLDOWN_MINUTES:
        errors.append(f"cooldown_minutes must be at least {MIN_COOLDOWN_MINUTES:g} (Rolimons cooldown).")
    if len(cfg.jitter_seconds) != 2 or not (0 <= cfg.jitter_seconds[0] <= cfg.jitter_seconds[1]):
        errors.append("jitter_seconds must be [min, max] with 0 <= min <= max.")
    if not 1 <= cfg.max_ads_per_24h <= 96:
        errors.append("max_ads_per_24h must be between 1 and 96.")
    if cfg.posting_hours.enabled:
        for label, value in (("start", cfg.posting_hours.start), ("end", cfg.posting_hours.end)):
            if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value.strip()):
                errors.append(f"posting_hours.{label} must be HH:MM (24-hour), got {value!r}.")
        if cfg.posting_hours.start.strip() == cfg.posting_hours.end.strip():
            errors.append("posting_hours start and end can't be the same time.")
    if cfg.value_mode.strategy not in ("warn", "pick"):
        errors.append('value_mode.strategy must be "warn" or "pick".')
    aa = cfg.auto_accept
    if aa.mode not in ("test", "live"):
        errors.append('auto_accept.mode must be "test" or "live".')
    if not 0 <= aa.max_per_day <= 50:
        errors.append("auto_accept.max_per_day must be between 0 and 50.")
    for label, gain in (("value", aa.min_value_gain), ("RAP", aa.min_rap_gain), ("price", aa.min_price_gain)):
        if gain is not None and not -100 <= gain <= 1000:
            errors.append(f"Auto-accept minimum {label} gain must be between -100% and 1000%.")
    if aa.enabled and aa.min_value_gain is None and aa.min_rap_gain is None and aa.min_price_gain is None:
        errors.append("Auto-accept needs at least one minimum gain (value, RAP or price).")
    if not cfg.ads:
        errors.append("No ads defined.")
    elif not cfg.enabled_ads():
        errors.append("All ads are disabled.")

    names = set()
    for ad in cfg.ads:
        label = f"Ad '{ad.name}'"
        if not ad.name:
            errors.append("Every ad needs a name.")
        elif ad.name in names:
            errors.append(f"{label}: duplicate name.")
        names.add(ad.name)
        if not 1 <= len(ad.offer_item_ids) <= MAX_OFFER_ITEMS:
            errors.append(f"{label}: must offer 1-{MAX_OFFER_ITEMS} items (has {len(ad.offer_item_ids)}).")
        slots = len(ad.request_item_ids) + len(ad.request_tags)
        if not 1 <= slots <= MAX_REQUEST_SLOTS:
            errors.append(f"{label}: request items + tags must total 1-{MAX_REQUEST_SLOTS} (has {slots}).")
        bad = [t for t in ad.request_tags if t not in VALID_TAGS]
        if bad:
            errors.append(f"{label}: unknown tag(s) {bad}. Valid: {', '.join(VALID_TAGS)}.")
        if len(set(ad.request_tags)) != len(ad.request_tags):
            errors.append(f"{label}: duplicate request tags.")
    return errors
