import argparse
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "live_engine"))


def _setup_logging(verbose: bool) -> None:
    from config.settings import Paths
    Paths.LOGS.mkdir(parents=True, exist_ok=True)
    log_file = Paths.LOGS / "agent.log"
    level = logging.DEBUG if verbose else logging.INFO
    handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7, encoding="utf-8")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), handler],
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
    os.environ["AGENT_MODE"] = "LIVE" if args.live else "SHADOW"
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
