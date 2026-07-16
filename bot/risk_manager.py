"""
risk_manager.py
Calculates 1.5R / 2R / 3R price levels and position size.
All risk is expressed as a percentage of the entry price.
"""

import math
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TradeLevels:
    """All price levels for a single trade."""
    entry:   float   # entry price (close of signal bar)
    sl:      float   # initial stop loss
    r_dist:  float   # 1R distance in price
    r1_5:    float   # 1.5R level → move SL to breakeven when hit
    r2:      float   # 2R level   → move SL to 1.5R when hit
    r3:      float   # 3R level   → close full position (full TP)
    direction: str   # 'LONG' or 'SHORT'


class RiskManager:
    def __init__(self, sl_pct: float, risk_per_trade_pct: float):
        """
        Parameters
        ----------
        sl_pct             : Stop loss distance as % of entry price  (e.g. 0.5 for 0.5%)
        risk_per_trade_pct : % of account balance risked per trade   (e.g. 1.0 for 1%)
        """
        self.sl_pct             = sl_pct
        self.risk_per_trade_pct = risk_per_trade_pct

    # ── Level Calculation ─────────────────────────────────────────────────────

    def calculate_levels(self, entry_price: float, direction: str) -> TradeLevels:
        """
        Build all price levels from entry and SL %.

        LONG  → SL below entry, R levels above entry
        SHORT → SL above entry, R levels below entry
        """
        r = entry_price * (self.sl_pct / 100)   # 1R in price units

        if direction == "LONG":
            sl   = entry_price - r
            r1_5 = entry_price + 1.5 * r
            r2   = entry_price + 2.0 * r
            r3   = entry_price + 3.0 * r
        else:  # SHORT
            sl   = entry_price + r
            r1_5 = entry_price - 1.5 * r
            r2   = entry_price - 2.0 * r
            r3   = entry_price - 3.0 * r

        levels = TradeLevels(
            entry=entry_price,
            sl=sl,
            r_dist=r,
            r1_5=r1_5,
            r2=r2,
            r3=r3,
            direction=direction,
        )
        logger.info(
            "Levels %s | Entry=%.4f | SL=%.4f | 1.5R=%.4f | 2R=%.4f | 3R=%.4f",
            direction, entry_price, sl, r1_5, r2, r3,
        )
        return levels

    # ── Position Sizing ───────────────────────────────────────────────────────

    def calculate_qty(self, balance_usdt: float, entry_price: float,
                      qty_step: float) -> float:
        """
        Risk-based position sizing.

        risk_amount ($) = balance × risk_pct
        R_price         = entry × sl_pct
        qty (base)      = risk_amount / R_price

        Example: balance=$500, risk=1%, entry=$60000, sl=0.5%
          risk_amount = $5
          R_price     = $300
          qty         = 5/300 = 0.01667 BTC  →  rounded down to step
        """
        risk_amount = balance_usdt * (self.risk_per_trade_pct / 100)
        r_price     = entry_price  * (self.sl_pct / 100)
        raw_qty     = risk_amount  / r_price

        # Round DOWN to nearest qty_step
        qty = math.floor(raw_qty / qty_step) * qty_step
        qty = round(qty, 8)

        logger.info(
            "Qty calc | balance=%.2f risk=$%.2f r_price=%.4f raw=%.6f rounded=%.6f step=%.6f",
            balance_usdt, risk_amount, r_price, raw_qty, qty, qty_step,
        )
        return qty
