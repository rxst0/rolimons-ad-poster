import sys
from pathlib import Path


def app_dir() -> Path:
    """Folder holding config.json/.env/logs: next to the .exe when frozen, else the project root."""
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
