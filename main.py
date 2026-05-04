"""Nifty Alpha Agent — entrypoint.

Usage:
    python main.py --shadow
    python main.py --live
    python main.py --replay --date 2026-05-04
    python main.py --replay --date 2026-05-04 --dataset /path/to/features.parquet
    python main.py --replay --date 2026-05-04 --speed 2
"""
import argparse
import logging
import os
import signal
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
    mode.add_argument("--replay", action="store_true", help="Replay historical date through live pipeline")
    parser.add_argument("--date", default=None, help="Date to replay: YYYY-MM-DD (required with --replay)")
    parser.add_argument("--dataset", default=None, help="Feature parquet path (optional, uses default OOS dataset)")
    parser.add_argument("--speed", type=float, default=0.0, help="Seconds to pause between bars (0=instant)")
    parser.add_argument("--dry-run", action="store_true", help="Log only, no orders")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    if args.replay:
        if not args.date:
            parser.error("--replay requires --date YYYY-MM-DD")
        os.environ["AGENT_MODE"] = "SHADOW"
        _setup_logging(args.verbose)
        from config.settings import Paths
        from replay import ReplayRunner
        runner = ReplayRunner(
            instrument="NIFTY",
            artifacts_dir=Paths.MODELS_SHADOW,
            replay_date=args.date,
            dataset_path=args.dataset,
            speed=args.speed,
        )
        runner.run()
        return

    os.environ["AGENT_MODE"] = "LIVE" if args.live else "SHADOW"
    _setup_logging(args.verbose)
    _lock_path = Path("/tmp/nifty_alpha_agent.lock")
    if _lock_path.exists():
        try:
            existing_pid = int(_lock_path.read_text().strip())
            os.kill(existing_pid, 0)  # raises OSError if dead
            # Process exists — check if it's suspended/zombie (stale) or actually running
            import subprocess
            state = subprocess.run(["ps", "-p", str(existing_pid), "-o", "state="],
                                   capture_output=True, text=True).stdout.strip()
            if state in ("T", "Z", ""):
                os.kill(existing_pid, signal.SIGKILL)
                print(f"Cleared suspended/zombie agent (PID {existing_pid}), taking over.")
            else:
                print(f"Agent already running (PID {existing_pid}, state={state}). Exiting.")
                sys.exit(1)
        except (OSError, ValueError):
            pass  # process is dead — stale lock, take over
    _lock_path.write_text(str(os.getpid()))
    import atexit
    atexit.register(_lock_path.unlink, missing_ok=True)
    from config.settings import Paths
    from engine import Engine
    Paths.DATA_DIRS["nifty"].mkdir(parents=True, exist_ok=True)
    Path("tokens").mkdir(exist_ok=True)
    if args.live:
        engine = Engine(instrument="NIFTY", artifacts_dir=Paths.MODELS_LIVE, live=True)
    else:
        engine = Engine(instrument="NIFTY", artifacts_dir=Paths.MODELS_SHADOW, live=False)
    engine.run()


if __name__ == "__main__":
    main()
