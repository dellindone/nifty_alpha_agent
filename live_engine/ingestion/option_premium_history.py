import logging

import numpy as np
import pandas as pd

from ingestion.synthetic_premium import synthetic_premium

logger = logging.getLogger(__name__)


def build_premium_history(
    price_df: pd.DataFrame,
    days_to_expiry: int = 7,
    risk_free_rate: float = 6.5,
) -> pd.DataFrame:
    """
    For each row in price_df, compute ATM CE and PE premium synthetically.
    price_df must already include a pre-merged `vix` column.
    Returns a DataFrame with columns: ce_premium, pe_premium
    Same index as price_df. Rows where computation fails get NaN.
    """
    required_columns = {"close", "vix"}
    missing_columns = required_columns.difference(price_df.columns)
    if missing_columns:
        missing_str = ", ".join(sorted(missing_columns))
        raise ValueError(
            f"price_df must contain columns: close, vix. Missing: {missing_str}"
        )

    premiums: list[dict[str, float]] = []

    for row in price_df.itertuples():
        result = synthetic_premium.compute_atm_premium(
            spot=row.close,
            days_to_expiry=days_to_expiry,
            volatility_pct=row.vix,
            risk_free_rate=risk_free_rate,
        )

        if result is None:
            premiums.append(
                {
                    "ce_premium": np.nan,
                    "pe_premium": np.nan,
                }
            )
            continue

        premiums.append(
            {
                "ce_premium": result.get("CE", np.nan),
                "pe_premium": result.get("PE", np.nan),
            }
        )

    return pd.DataFrame(premiums, index=price_df.index)
