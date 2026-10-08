"""Command-line Rolimons trade ad auto-poster.

    python main.py            validate, then post ads on a timer until Ctrl+C
    python main.py --check    validate cookie/config/items and print values; post nothing
    python main.py --once     post a single ad, then exit
"""
import argparse
import sys
from pathlib import Path

import requests

from roliposter.paths import config_path, log_dir
from roliposter.logsetup import setup_logging
from roliposter.poster import AuthError, Poster
from roliposter.startup import StartupError, prepare


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rolimons trade ad auto-poster (Rolimons ads only).")
    p.add_argument("--config", type=Path, default=config_path(), help="path to config.json")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="validate everything, post nothing")
    group.add_argument("--once", action="store_true", help="post one ad and exit")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    log = setup_logging(log_dir())
    session = requests.Session()
    poster = None
    try:
        cfg, cookie, catalog = prepare(args.config, session)
        if args.check:
            log.info("Check complete. Nothing was posted.")
            return 0
        poster = Poster(cfg, args.config, cookie, catalog, session=session)
        if args.once:
            return 0 if poster.post_once() else 1
        log.info("Press Ctrl+C to stop.")
        poster.run()
        return 0
    except StartupError as e:
        log.error("%s", e)
        return 2
    except AuthError as e:
        log.error("AUTH FAILED: Rolimons rejected your verification cookie (%s).", e)
        log.error("Your _RoliVerification cookie is missing, invalid or expired. Log in to rolimons.com, "
                  "re-verify, copy the new cookie value into .env, then restart. Stopped.")
        return 3
    except KeyboardInterrupt:
        if poster:
            poster.stop()
        log.info("Ctrl+C received. Shut down cleanly.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
