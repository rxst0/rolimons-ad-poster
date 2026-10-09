import os
import sys
from pathlib import Path

HOME_ENV_VAR = "ROLIPOSTER_HOME"


def app_dir() -> Path:
    """Folder holding config.json/.env/logs: $ROLIPOSTER_HOME (set by the Android app), next to the
    .exe when frozen, else the project root."""
    if os.environ.get(HOME_ENV_VAR):
        return Path(os.environ[HOME_ENV_VAR])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return app_dir() / "config.json"


def env_path() -> Path:
    return app_dir() / ".env"


def state_path() -> Path:
    return app_dir() / "state.json"


def log_dir() -> Path:
    return app_dir() / "logs"


def cache_dir() -> Path:
    return app_dir() / "cache"


def resource_path(relative: str) -> Path:
    """Bundled read-only files (e.g. the icon): inside the PyInstaller bundle when frozen."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative
