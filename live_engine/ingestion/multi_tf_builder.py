import logging
from pathlib import Path

import pandas as pd
from config.settings import IST
from config.settings import Paths

logger = logging.getLogger(__name__)


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame.columns = [str(c).lower() for c in frame.columns]
    return frame.sort_index()


def _filter_nse_session(frame: pd.DataFrame, interval: str) -> pd.DataFrame:
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return frame
    interval_lower = str(interval).lower()
    if interval_lower in ("d", "1d", "w", "1w", "m", "1m") or interval_lower.endswith(("wk", "mo")):
        return frame
    local_index = frame.index.tz_convert(IST) if frame.index.tz else frame.index.tz_localize(IST)
    minutes = local_index.hour * 60 + local_index.minute
    mask = (minutes >= 555) & (minutes <= 930)
    return frame.loc[mask].copy()


class MultiTFBuilder:
    _resolution_map = {
        "5": "5m",
        "15": "15m",
        "60": "60m",
        "D": "D",
    }

    def _load_frame(self, path: Path, interval: str) -> pd.DataFrame:
        frame = pd.read_parquet(path)
        frame = _normalize_columns(frame)

        if not isinstance(frame.index, pd.DatetimeIndex):
            frame.index = pd.to_datetime(frame.index, utc=True)
        elif frame.index.tz is None:
            frame.index = frame.index.tz_localize("UTC")
        else:
            frame.index = frame.index.tz_convert("UTC")

        frame = _filter_nse_session(frame, interval)

        expected_columns = ["open", "high", "low", "close", "volume"]
        available_columns = [column for column in expected_columns if column in frame.columns]
        return frame.loc[:, available_columns]

    def _attach_vix_5m(self, instrument_key: str, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        if instrument_key == "INDIAVIX":
            return frames

        frame_5m = frames.get("5m")
        if frame_5m is None or frame_5m.empty:
            return frames

        vix_path = DATA_DIR / "INDIAVIX_5.parquet"
        if not vix_path.exists():
            logger.warning("Raw parquet missing for INDIAVIX 5m at %s", vix_path)
            return frames

        vix_frame = self._load_frame(vix_path, "5m")
        if vix_frame.empty or "close" not in vix_frame.columns:
            logger.warning("INDIAVIX 5m parquet is empty or missing close column at %s", vix_path)
            return frames

        left = frame_5m.sort_index().reset_index().rename(columns={"index": "timestamp"})
        right = (
            vix_frame[["close"]]
            .rename(columns={"close": "vix"})
            .sort_index()
            .reset_index()
            .rename(columns={"index": "timestamp"})
        )

        merged = pd.merge_asof(left, right, on="timestamp", direction="backward")
        frames["5m"] = merged.set_index("timestamp").sort_index()
        return frames

    def build(self, instrument: str) -> dict[str, pd.DataFrame]:
        """
        Load raw parquet files for `instrument` (e.g. "NIFTY") and return a dict:
        {
            "5m":  DataFrame,
            "15m": DataFrame,
            "60m": DataFrame,
            "D":   DataFrame,
        }
        15m/60m/D DataFrames have columns: open, high, low, close, volume.
        5m DataFrame has: open, high, low, close, volume and, when
        INDIAVIX_5.parquet is available, an additional `vix` column.
        Index: DatetimeIndex (UTC)
        """
        frames: dict[str, pd.DataFrame] = {}
        instrument_key = instrument.upper()

        for resolution, tf_name in self._resolution_map.items():
            path = DATA_DIR / f"{instrument_key}_{resolution}.parquet"
            if not path.exists():
                logger.warning("Raw parquet missing for instrument=%s resolution=%s at %s", instrument_key, resolution, path)
                continue

            frames[tf_name] = self._load_frame(path, tf_name)

        return self._attach_vix_5m(instrument_key, frames)


multi_tf_builder = MultiTFBuilder()
