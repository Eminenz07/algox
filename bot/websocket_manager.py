"""
websocket_manager.py
Manages two Bybit WebSocket connections:
  1. PUBLIC  — kline.15 (signal detection) + tickers (real-time price for R levels)
  2. PRIVATE — position stream (SL hit detection)

Flow:
  kline confirm=True → fetch candles → strategy.detect_signal → trade_manager.on_signal
  ticker update      → trade_manager.on_price_update
  position size→0    → trade_manager.on_position_closed
"""

import logging
import threading
import time

import pandas as pd
from pybit.unified_trading import WebSocket

from strategy     import detect_signal
from exchange     import BybitClient

logger = logging.getLogger(__name__)

# Tracks the last DataFrame per symbol so we can append confirmed candles
_candle_store: dict[str, pd.DataFrame] = {}
_candle_lock  = threading.Lock()


class WebSocketManager:
    def __init__(self,
                 api_key:      str,
                 api_secret:   str,
                 demo:         bool,
                 symbols:      list[str],
                 exchange:     BybitClient,
                 trade_manager,           # TradeManager (type hint avoids circular import)
                 config:       dict):
        self.api_key      = api_key
        self.api_secret   = api_secret
        self.demo         = demo
        self.symbols      = symbols
        self.exchange     = exchange
        self.tm           = trade_manager
        self.cfg          = config

        self._ws_public:  WebSocket | None = None
        self._ws_private: WebSocket | None = None

        # Seed candle history for each symbol on startup
        self._init_candle_store()

    # ── Startup ───────────────────────────────────────────────────────────────

    def _init_candle_store(self):
        """Fetch historical candles via REST on startup."""
        tf = self.cfg["trading"]["timeframe"]
        for sym in self.symbols:
            df = self.exchange.get_candles(sym, interval=tf, limit=200)
            if not df.empty:
                with _candle_lock:
                    _candle_store[sym] = df
                logger.info("Seeded %d candles for %s", len(df), sym)
            else:
                logger.warning("Could not seed candles for %s", sym)

    def start(self):
        """Connect both WebSockets. Returns immediately (runs in background threads)."""
        self._connect_public()
        self._connect_private()
        logger.info("WebSocket manager started for %s", self.symbols)

    # ── Public WebSocket ──────────────────────────────────────────────────────

    def _connect_public(self):
        tf = self.cfg["trading"]["timeframe"]
        self._ws_public = WebSocket(
            testnet=False,
            demo=self.demo,
            channel_type="linear",
        )
        for sym in self.symbols:
            # Kline stream — fires on every tick but we act only on confirm=True
            self._ws_public.kline_stream(
                interval=int(tf),
                symbol=sym,
                callback=self._on_kline,
            )
            # Ticker stream — real-time last price for R-level monitoring
            self._ws_public.ticker_stream(
                symbol=sym,
                callback=self._on_ticker,
            )

    # ── Private WebSocket ─────────────────────────────────────────────────────

    def _connect_private(self):
        self._ws_private = WebSocket(
            testnet=False,
            demo=self.demo,
            api_key=self.api_key,
            api_secret=self.api_secret,
            channel_type="private",
        )
        self._ws_private.position_stream(callback=self._on_position)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_kline(self, msg: dict):
        """
        Fires for every candle update.
        We only act when confirm=True (candle has fully closed).
        """
        try:
            for candle in msg.get("data", []):
                if not candle.get("confirm", False):
                    return  # candle still forming

                symbol = msg["topic"].split(".")[-1]   # e.g. "kline.15.BTCUSDT" → "BTCUSDT"
                new_row = {
                    "timestamp": int(candle["start"]),
                    "open":      float(candle["open"]),
                    "high":      float(candle["high"]),
                    "low":       float(candle["low"]),
                    "close":     float(candle["close"]),
                    "volume":    float(candle["volume"]),
                }

                # Append to candle store and keep last 300 bars
                with _candle_lock:
                    df = _candle_store.get(symbol, pd.DataFrame())
                    new_df = pd.DataFrame([new_row])
                    df = pd.concat([df, new_df], ignore_index=True).tail(300)
                    _candle_store[symbol] = df

                logger.debug("Candle closed %s close=%.4f", symbol, new_row["close"])

                # Run signal detection in a separate thread to not block WS
                threading.Thread(
                    target=self._check_signal,
                    args=(symbol, df.copy()),
                    daemon=True,
                ).start()

        except Exception as exc:
            logger.error("_on_kline error: %s", exc)

    def _check_signal(self, symbol: str, df: pd.DataFrame):
        """Run ALMA crossover check and open a trade if signal fires."""
        cfg_s = self.cfg["strategy"]
        signal = detect_signal(
            df,
            length=cfg_s["ma_period"],
            offset=cfg_s["alma_offset"],
            sigma=cfg_s["alma_sigma"],
        )
        if not signal:
            return

        logger.info("Signal: %s %s", signal, symbol)

        # Get current balance for position sizing
        balance = self.exchange.get_equity()
        if balance <= 0:
            logger.error("Balance is 0 — cannot size position")
            return

        # Delegate to trade manager
        self.tm.on_signal(symbol, signal, balance)

    def _on_ticker(self, msg: dict):
        """Real-time price update — used to monitor 1.5R / 2R / 3R levels."""
        try:
            data = msg.get("data", {})
            symbol = data.get("symbol") or msg.get("topic", "").split(".")[-1]
            last_price = data.get("lastPrice")
            if last_price and symbol:
                self.tm.on_price_update(symbol, float(last_price))
        except Exception as exc:
            logger.error("_on_ticker error: %s", exc)

    def _on_position(self, msg: dict):
        """
        Private position stream.
        Detects when a position is closed (size = 0) — signals SL hit.
        """
        try:
            for pos in msg.get("data", []):
                symbol = pos.get("symbol")
                size   = float(pos.get("size", 1))
                if symbol and size == 0 and self.tm.has_trade(symbol):
                    avg_price = float(pos.get("avgPrice", 0))
                    logger.info("Position closed externally: %s (price~%.4f)", symbol, avg_price)
                    # Run in thread so WS callback returns fast
                    threading.Thread(
                        target=self.tm.on_position_closed,
                        args=(symbol, avg_price),
                        daemon=True,
                    ).start()
        except Exception as exc:
            logger.error("_on_position error: %s", exc)

    # ── Graceful Shutdown ─────────────────────────────────────────────────────

    def stop(self):
        try:
            if self._ws_public:
                self._ws_public.exit()
            if self._ws_private:
                self._ws_private.exit()
        except Exception as exc:
            logger.warning("WebSocket stop error: %s", exc)
