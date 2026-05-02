"""Nifty Alpha Agent — entrypoint.

Usage:
    python main.py --shadow
    python main.py --live
    python main.py --shadow --dry-run
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "live_engine"))


def _setup_logging(verbose: bool) -> None:
    from config.settings import Paths
    Paths.LOGS.mkdir(parents=True, exist_ok=True)
    log_file = Paths.LOGS / "agent.log"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")],
    )
    sys.stderr = open(log_file, "a", encoding="utf-8", buffering=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nifty Alpha Agent")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--shadow", action="store_true", help="Paper trade")
    mode.add_argument("--live", action="store_true", help="Live trading")
    parser.add_argument("--dry-run", action="store_true", help="Log only, no orders")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()
    _setup_logging(args.verbose)
    from config.settings import Paths
    from engine import Engine
    Paths.DATA_DIRS["nifty"].mkdir(parents=True, exist_ok=True)
    Path("tokens").mkdir(exist_ok=True)
    if args.live:
        engine = Engine(instrument="NIFTY", artifacts_dir=Paths.MODELS, live=True)
    else:
        engine = Engine(instrument="NIFTY", artifacts_dir=Paths.MODELS, live=False)
    engine.run()


if __name__ == "__main__":
    main()
