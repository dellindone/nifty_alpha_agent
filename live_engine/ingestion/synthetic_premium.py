import logging

import mibian

logger = logging.getLogger(__name__)


class SyntheticPremium:
    def compute(
        self,
        spot: float,
        strike: float,
        days_to_expiry: int,
        volatility_pct: float,
        risk_free_rate: float = 6.5,
        option_type: str = "CE",
    ) -> float | None:
        """Return theoretical premium in Rs. Returns None on error."""
        try:
            option = mibian.BS(
                [spot, strike, risk_free_rate, days_to_expiry],
                volatility=volatility_pct,
            )

            if option_type.upper() == "CE":
                premium = option.callPrice
            elif option_type.upper() == "PE":
                premium = option.putPrice
            else:
                logger.error("Unsupported option_type=%s", option_type)
                return None

            return float(premium) if premium is not None else None
        except Exception as exc:
            logger.error(
                "Synthetic premium compute failed for spot=%s strike=%s dte=%s iv=%s option_type=%s: %s",
                spot,
                strike,
                days_to_expiry,
                volatility_pct,
                option_type,
                exc,
            )
            return None

    def compute_atm_premium(
        self,
        spot: float,
        days_to_expiry: int,
        volatility_pct: float,
        risk_free_rate: float = 6.5,
        strike_gap: int = 50,
    ) -> dict | None:
        """Return {"CE": float, "PE": float} for ATM strike. Returns None on error."""
        try:
            atm_strike = round(spot / strike_gap) * strike_gap
            call_premium = self.compute(
                spot=spot,
                strike=atm_strike,
                days_to_expiry=days_to_expiry,
                volatility_pct=volatility_pct,
                risk_free_rate=risk_free_rate,
                option_type="CE",
            )
            put_premium = self.compute(
                spot=spot,
                strike=atm_strike,
                days_to_expiry=days_to_expiry,
                volatility_pct=volatility_pct,
                risk_free_rate=risk_free_rate,
                option_type="PE",
            )

            if call_premium is None or put_premium is None:
                return None

            return {
                "CE": call_premium,
                "PE": put_premium,
            }
        except Exception as exc:
            logger.error(
                "Synthetic ATM premium compute failed for spot=%s dte=%s iv=%s strike_gap=%s: %s",
                spot,
                days_to_expiry,
                volatility_pct,
                strike_gap,
                exc,
            )
            return None


synthetic_premium = SyntheticPremium()
