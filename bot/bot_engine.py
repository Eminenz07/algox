"""
bot_engine.py
Polling-based engine — replaces WebSocket approach.

Why polling? pybit 5.17.x has a broken demo WebSocket URL (returns 404).
The REST API works perfectly, so we use it for everything:

  • Signal thread   — waits for each 15-min candle close, then runs ALMA check
  • Price thread    — polls last price every 5 s to monitor 1.5R / 2R / 3R levels
  • Position thread — polls position every 15 s to detect SL hits (size → 0)
"""

import logging
import threading
import time
import datetime

from exchange      import BybitClient
from strategy      import detect_signal
from trade_manager import TradeManager

logger = logging.getLogger(__name__)


class BotEngine:
    def __init__(self,
                 exchange:      BybitClient,
                 trade_manager: TradeManager,
                 symbols:       list[str],
                 config:        dict):
        self.exchange      = exchange
        self.tm            = trade_manager
        self.symbols       = symbols
        self.cfg           = config
        self.running       = False

        # Candle DataFrame cache, seeded on start
        self._candles: dict = {}    # symbol → pd.DataFrame

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        """Seed candle history, then launch all background threads."""
        self._seed_candles()
        self.running = True

        threads = [
            threading.Thread(target=self._signal_loop,   name="signal-loop",   daemon=True),
            threading.Thread(target=self._price_loop,    name="price-loop",    daemon=True),
            threading.Thread(target=self._position_loop, name="position-loop", daemon=True),
        ]
        for t in threads:
            t.start()

        logger.info("BotEngine started - %d symbols, polling mode", len(self.symbols))

    def stop(self):
        self.running = False

    # ── Candle seeding ────────────────────────────────────────────────────────

    def _seed_candles(self):
        tf = self.cfg["trading"]["timeframe"]
        use_alt = self.cfg["strategy"].get("use_alternate_signals", False)
        limit   = 800 if use_alt else 200
        for sym in self.symbols:
            df = self.exchange.get_candles(sym, interval=tf, limit=limit)
            if not df.empty:
                self._candles[sym] = df
                logger.info("Seeded %d candles for %s", len(df), sym)
            else:
                logger.warning("Could not seed candles for %s", sym)

    # ── Signal thread ─────────────────────────────────────────────────────────

    def _signal_loop(self):
        """
        Sleep until the next 15-min candle CLOSES, then run ALMA signal check.
        Adds a 5-second buffer after close to ensure the REST API has the
        completed candle available.
        """
        tf_minutes = int(self.cfg["trading"]["timeframe"])   # 15

        while self.running:
            wait = self._seconds_to_next_candle(tf_minutes)
            logger.info("Next signal check in %.0fs  (%.1f min)",
                        wait, wait / 60)
            time.sleep(wait)

            if not self.running:
                break

            for sym in self.symbols:
                try:
                    self._check_signal(sym)
                except Exception as exc:
                    logger.error("Signal check error %s: %s", sym, exc)

    def _seconds_to_next_candle(self, tf_minutes: int) -> float:
        """
        Return how many seconds until the next tf_minutes-period candle closes.
        Example: at 14:07:30 on a 15-min chart, next close is 14:15:00 → 457.5 s
        """
        now     = datetime.datetime.utcnow()
        total_s = now.minute * 60 + now.second + now.microsecond / 1_000_000
        period_s = tf_minutes * 60
        elapsed_in_period = total_s % period_s
        remaining = period_s - elapsed_in_period
        BUFFER = 5.0   # seconds after close to wait for REST API to update
        return remaining + BUFFER

    def _check_signal(self, symbol: str):
        """Fetch fresh candles, run ALMA, enter trade if signal fires."""
        tf  = self.cfg["trading"]["timeframe"]
        use_alt = self.cfg["strategy"].get("use_alternate_signals", False)
        limit   = 800 if use_alt else 200
        df  = self.exchange.get_candles(symbol, interval=tf, limit=limit)
        if df.empty:
            return

        self._candles[symbol] = df    # refresh cache

        cfg_s  = self.cfg["strategy"]
        # Drop the last row (active, unfinished candle) to prevent repainting/false signals
        closed_df = df.iloc[:-1]
        signal = detect_signal(
            closed_df,
            length = cfg_s["ma_period"],
            offset = cfg_s["alma_offset"],
            sigma  = cfg_s["alma_sigma"],
            use_alternate_signals = use_alt,
            alternate_signals_multiplier = cfg_s.get("alternate_signals_multiplier", 10),
            timeframe = tf,
        )

        if not signal:
            return

        logger.info("[SIGNAL] %s %s", signal, symbol)

        # Check if already in trade
        if self.tm.has_trade(symbol):
            logger.info("Signal %s %s ignored — already in trade", signal, symbol)
            return

        # Check active trading pairs configuration
        active_pairs = self.cfg["trading"].get("active_trading_pairs", self.symbols)
        if symbol not in active_pairs:
            msg = f"🔔 <b>[SIGNAL ONLY]</b> {symbol} {signal} signal detected.\n(Trading is disabled for this pair)"
            logger.info(msg.replace("<b>", "").replace("</b>", ""))
            self.tm.notifier.info(msg)
            return

        # Check max concurrent trades limit
        active_count = self.tm.active_count()
        max_trades   = self.cfg["trading"].get("max_concurrent_trades", 2)
        if active_count >= max_trades:
            msg = f"🔔 <b>[SIGNAL ONLY]</b> {symbol} {signal} signal detected.\n(Max concurrent trades of {max_trades} reached)"
            logger.info(msg.replace("<b>", "").replace("</b>", ""))
            self.tm.notifier.info(msg)
            return

        balance = self.exchange.get_equity()
        if balance <= 0:
            logger.error("Balance $0 — cannot open trade")
            return

        self.tm.on_signal(symbol, signal, balance)

    # ── Price monitoring thread ───────────────────────────────────────────────

    def _price_loop(self):
        """
        Poll last price every 5 seconds for each symbol that has an open trade.
        Feeds trade_manager so it can trigger SL trailing when 1.5R / 2R / 3R hit.
        """
        while self.running:
            for sym in self.symbols:
                if not self.tm.has_trade(sym):
                    continue
                try:
                    price = self.exchange.get_last_price(sym)
                    if price:
                        self.tm.on_price_update(sym, price)
                except Exception as exc:
                    logger.error("Price poll error %s: %s", sym, exc)
            time.sleep(5)

    # ── Position monitoring thread ────────────────────────────────────────────

    def _position_loop(self):
        """
        Poll position every 15 seconds.
        Synchronises live position state between memory and Bybit exchange.
        """
        while self.running:
            for sym in self.symbols:
                try:
                    pos = self.exchange.get_position(sym)
                    has_local = self.tm.has_trade(sym)

                    # Case A: We have an active position on exchange
                    if pos and float(pos.get("size", 0)) > 0:
                        if not has_local:
                            logger.info("Found active position for %s on exchange not tracked locally -> syncing...", sym)
                            self.tm.sync_positions([sym])
                        else:
                            # Update live qty and unrealised PnL on existing local trade object
                            with self.tm._lock:
                                trade = self.tm._trades.get(sym)
                                if trade:
                                    trade.qty = float(pos["size"])
                                    trade.pnl = float(pos.get("unrealisedPnl") or 0.0)
                    
                    # Case B: No active position on exchange
                    else:
                        if has_local:
                            logger.info("Position gone for %s on exchange -> closing locally", sym)
                            self.tm.on_position_closed(sym, close_price=0.0)

                except Exception as exc:
                    logger.error("Position poll error %s: %s", sym, exc)
            time.sleep(15)
