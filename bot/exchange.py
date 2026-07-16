"""
exchange.py
Bybit Unified Trading Account (UTA) REST API wrapper.
Handles candle fetching, order placement, position management, and SL updates.
"""

import time
import logging
import math
import pandas as pd
from pybit.unified_trading import HTTP

logger = logging.getLogger(__name__)


class BybitClient:
    def __init__(self, api_key: str, api_secret: str, demo: bool = True):
        self.session = HTTP(
            testnet=False,
            demo=demo,
            api_key=api_key,
            api_secret=api_secret,
        )
        # Cache symbol info (qty step, min qty, price precision)
        self._symbol_info: dict[str, dict] = {}

    # ── Symbol Info ───────────────────────────────────────────────────────────

    def get_symbol_info(self, symbol: str) -> dict:
        """Fetch and cache lot size / tick size for a symbol."""
        if symbol in self._symbol_info:
            return self._symbol_info[symbol]
        try:
            resp = self.session.get_instruments_info(category="linear", symbol=symbol)
            item = resp["result"]["list"][0]
            lot  = item["lotSizeFilter"]
            info = {
                "qty_step":  float(lot["qtyStep"]),
                "min_qty":   float(lot["minOrderQty"]),
                "tick_size": float(item["priceFilter"]["tickSize"]),
            }
            self._symbol_info[symbol] = info
            logger.info("Symbol info %s: %s", symbol, info)
            return info
        except Exception as exc:
            logger.error("get_symbol_info failed for %s: %s", symbol, exc)
            return {"qty_step": 0.001, "min_qty": 0.001, "tick_size": 0.1}

    def round_price(self, symbol: str, price: float) -> float:
        """Round a price to the symbol's tick size."""
        tick = self.get_symbol_info(symbol)["tick_size"]
        return round(math.floor(price / tick) * tick, 8)

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_candles(self, symbol: str, interval: str = "15",
                    limit: int = 200) -> pd.DataFrame:
        """
        Fetch OHLCV candles. Returns DataFrame ordered oldest→newest.
        Columns: timestamp, open, high, low, close, volume
        """
        try:
            resp = self.session.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
            raw = resp["result"]["list"]
            df  = pd.DataFrame(raw, columns=[
                "timestamp", "open", "high", "low", "close", "volume", "turnover"
            ])
            df = df.astype({
                "timestamp": "int64",
                "open": "float64", "high": "float64",
                "low": "float64",  "close": "float64",
                "volume": "float64",
            })
            # Bybit returns newest first — reverse to oldest first
            df = df.iloc[::-1].reset_index(drop=True)
            return df
        except Exception as exc:
            logger.error("get_candles failed for %s: %s", symbol, exc)
            return pd.DataFrame()

    def get_last_price(self, symbol: str) -> float | None:
        """Fetch the current last traded price."""
        try:
            resp = self.session.get_tickers(category="linear", symbol=symbol)
            return float(resp["result"]["list"][0]["lastPrice"])
        except Exception as exc:
            logger.error("get_last_price failed for %s: %s", symbol, exc)
            return None

    # ── Account ───────────────────────────────────────────────────────────────

    def get_usdt_balance(self) -> float:
        """Return USDT wallet balance (walletBalance) in Unified Account."""
        try:
            resp = self.session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
            coins = resp["result"]["list"][0]["coin"]
            for c in coins:
                if c["coin"] == "USDT":
                    val = c.get("walletBalance") or c.get("equity")
                    return float(val) if val else 0.0
            return 0.0
        except Exception as exc:
            logger.error("get_usdt_balance failed: %s", exc)
            return 0.0

    def get_equity(self) -> float:
        """
        Return the equity of USDT (the margin coin) rather than total Unified Account equity.
        This ensures risk sizing (e.g. 1% risk) is calculated against our actual USDT capital.
        """
        try:
            resp = self.session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
            coins = resp["result"]["list"][0]["coin"]
            for c in coins:
                if c["coin"] == "USDT":
                    val = c.get("equity") or c.get("walletBalance")
                    return float(val) if val else 0.0
            return 0.0
        except Exception as exc:
            logger.error("get_equity failed: %s", exc)
            return 0.0

    # ── Position ──────────────────────────────────────────────────────────────

    def get_position(self, symbol: str) -> dict | None:
        """Return the current position dict or None if flat. Raises exception on network failure."""
        resp = self.session.get_positions(category="linear", symbol=symbol)
        for pos in resp["result"]["list"]:
            if float(pos["size"]) > 0:
                return pos
        return None

    # ── Setup ─────────────────────────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol. Silently ignores 'already set' errors."""
        try:
            self.session.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            logger.info("Leverage set to %dx for %s", leverage, symbol)
            return True
        except Exception as exc:
            msg = str(exc)
            if "110043" in msg or "leverage not modified" in msg.lower():
                # Already at the correct leverage — this is fine
                logger.info("Leverage already at %dx for %s", leverage, symbol)
                return True
            logger.warning("set_leverage %s: %s", symbol, repr(msg[:120]))
            return False

    def set_isolated_margin(self, symbol: str, leverage: int) -> bool:
        """
        Switch symbol to isolated margin mode.
        Tries multiple pybit method names for compatibility across versions.
        """
        lev = str(leverage)
        tried = []
        # pybit 5.x V5 API — try known method names
        for method_name in ("switch_isolated_margin", "set_margin_mode"):
            fn = getattr(self.session, method_name, None)
            if fn is None:
                continue
            tried.append(method_name)
            try:
                if method_name == "switch_isolated_margin":
                    fn(category="linear", symbol=symbol,
                       tradeMode=1, buyLeverage=lev, sellLeverage=lev)
                else:
                    fn(setMarginMode="ISOLATED_MARGIN")
                logger.info("Isolated margin enabled for %s via %s", symbol, method_name)
                return True
            except Exception as exc:
                msg = str(exc)
                if "110043" in msg or "not modified" in msg.lower():
                    logger.info("Margin mode already isolated for %s", symbol)
                    return True
                logger.warning("%s %s: %s", method_name, symbol, repr(msg[:100]))
        if not tried:
            logger.warning("No margin-mode method found in pybit for %s — skipping", symbol)
        return False

    # ── Order Management ──────────────────────────────────────────────────────

    def place_market_entry(self, symbol: str, direction: str, qty: float) -> str | None:
        """
        Place a market entry order.
        Returns Bybit orderId on success, None on failure.
        """
        side = "Buy" if direction == "LONG" else "Sell"
        try:
            resp = self.session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                positionIdx=0,      # one-way mode
                reduceOnly=False,
            )
            order_id = resp["result"]["orderId"]
            logger.info("Market entry placed | %s %s qty=%s id=%s", direction, symbol, qty, order_id)
            return order_id
        except Exception as exc:
            logger.error("place_market_entry failed %s %s: %s", direction, symbol, exc)
            return None

    def set_stop_loss(self, symbol: str, sl_price: float) -> bool:
        """
        Set (or update) the stop loss on the current position.
        Uses set_trading_stop — no order cancellation needed on update.
        """
        sl_str = str(self.round_price(symbol, sl_price))
        try:
            self.session.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss=sl_str,
                slTriggerBy="LastPrice",
                positionIdx=0,
            )
            logger.info("SL set to %s for %s", sl_str, symbol)
            return True
        except Exception as exc:
            logger.error("set_stop_loss failed %s: %s", symbol, exc)
            return False

    def remove_stop_loss(self, symbol: str) -> bool:
        """Remove the stop loss from the current position."""
        try:
            self.session.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss="0",
                positionIdx=0,
            )
            return True
        except Exception as exc:
            logger.error("remove_stop_loss failed %s: %s", symbol, exc)
            return False

    def close_position(self, symbol: str, direction: str, qty: float) -> bool:
        """
        Close a position with a reduce-only market order.
        direction: 'LONG' or 'SHORT'
        """
        close_side = "Sell" if direction == "LONG" else "Buy"
        try:
            resp = self.session.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=str(qty),
                positionIdx=0,
                reduceOnly=True,
            )
            logger.info("Position closed | %s %s qty=%s", direction, symbol, qty)
            return True
        except Exception as exc:
            logger.error("close_position failed %s %s: %s", direction, symbol, exc)
            return False

    def get_filled_entry_price(self, symbol: str, order_id: str,
                               max_wait: float = 5.0) -> float | None:
        """
        Poll order fills until the entry order is filled.
        Returns the average fill price or None on timeout.
        """
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                resp = self.session.get_order_history(
                    category="linear",
                    symbol=symbol,
                    orderId=order_id,
                    limit=1,
                )
                for o in resp["result"]["list"]:
                    if o["orderStatus"] == "Filled":
                        return float(o["avgPrice"])
            except Exception as exc:
                logger.warning("get_filled_entry_price error: %s", exc)
            time.sleep(0.25)
        logger.error("Entry order %s not filled within %.1fs", order_id, max_wait)
        return None
