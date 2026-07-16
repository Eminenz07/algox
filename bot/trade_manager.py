"""
trade_manager.py
Per-symbol trailing SL state machine.

State machine:
  FLAT (0)
  ├─ Long signal  → LONG_ACTIVE  (SL placed at entry-R, watching 1.5R)
  │    ├─ 1.5R hit → LONG_BE     (SL moved to breakeven,  watching 2R)
  │    ├─ 2R hit   → LONG_LOCKED (SL moved to 1.5R level, watching 3R)
  │    ├─ 3R hit   → FLAT        (close position = full TP win)
  │    └─ SL hit   → FLAT        (detected via position stream → size=0)
  └─ Short signal → SHORT_ACTIVE / SHORT_BE / SHORT_LOCKED  (mirror)
"""

import time
import logging
import threading
import os
import json
from dataclasses import dataclass, field
from typing import Callable

from exchange     import BybitClient
from risk_manager import RiskManager, TradeLevels
from notifier     import Notifier

logger = logging.getLogger(__name__)

# ── State constants ────────────────────────────────────────────────────────────
FLAT          = 0
LONG_ACTIVE   = 1.0
LONG_BE       = 1.5
LONG_LOCKED   = 2.0
SHORT_ACTIVE  = -1.0
SHORT_BE      = -1.5
SHORT_LOCKED  = -2.0


@dataclass
class Trade:
    symbol:    str
    direction: str         # 'LONG' or 'SHORT'
    entry:     float
    qty:       float
    state:     float       # one of the constants above
    levels:    TradeLevels
    open_time: float = field(default_factory=time.time)
    pnl:       float = 0.0


class TradeManager:
    def __init__(self,
                 exchange:         BybitClient,
                 risk_manager:     RiskManager,
                 notifier:         Notifier,
                 max_trades:       int  = 2,
                 trade_direction:  str  = "BOTH",
                 be_offset_r:      float = 0.1):
        self.exchange        = exchange
        self.risk_manager    = risk_manager
        self.notifier        = notifier
        self.max_trades      = max_trades
        self.trade_direction = trade_direction
        self.be_offset_r     = be_offset_r

        self._trades: dict[str, Trade] = {}   # symbol → Trade
        self._lock   = threading.Lock()
        self._history: list[dict] = []        # closed trades for dashboard
        self._load_history()

        # External callback called whenever state changes (for dashboard)
        self.on_state_change: Callable | None = None

    def _load_history(self):
        """Load closed trades history from history.json if exists."""
        history_path = "history.json"
        if os.path.exists(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    self._history = json.load(f)
                logger.info("Loaded %d closed trades from history.json", len(self._history))
            except Exception as exc:
                logger.warning("Failed to load history.json: %s", exc)
        else:
            self._history = []

    def _save_history(self):
        """Save closed trades history to history.json."""
        history_path = "history.json"
        try:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(self._history, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to save history.json: %s", exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    def active_count(self) -> int:
        with self._lock:
            return len(self._trades)

    def has_trade(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._trades

    def get_trade(self, symbol: str) -> Trade | None:
        with self._lock:
            return self._trades.get(symbol)

    def get_all_trades(self) -> list[dict]:
        """Snapshot for dashboard / WebSocket push."""
        with self._lock:
            out = []
            for t in self._trades.values():
                out.append({
                    "symbol":    t.symbol,
                    "direction": t.direction,
                    "entry":     t.entry,
                    "qty":       t.qty,
                    "state":     t.state,
                    "sl":        t.levels.sl,
                    "r1_5":      t.levels.r1_5,
                    "r2":        t.levels.r2,
                    "r3":        t.levels.r3,
                    "pnl":       t.pnl,
                    "open_time": t.open_time,
                })
            return out

    def get_history(self) -> list[dict]:
        with self._lock:
            return list(self._history[-50:])  # last 50 trades

    def sync_positions(self, symbols: list[str]):
        """
        Synchronise memory state with Bybit's actual open positions on startup.
        Reconstructs the Trade object and determines the trailing SL state.
        """
        for symbol in symbols:
            try:
                pos = self.exchange.get_position(symbol)
                if not pos:
                    continue

                size = float(pos["size"])
                if size <= 0:
                    continue

                direction = "LONG" if pos["side"] == "Buy" else "SHORT"
                entry = float(pos["avgPrice"])
                
                # Reconstruct Trade levels
                levels = self.risk_manager.calculate_levels(entry, direction)
                
                # Determine state from active stop loss on exchange
                exchange_sl = float(pos.get("stopLoss") or 0)
                
                if direction == "LONG":
                    state = LONG_ACTIVE
                    if exchange_sl > 0:
                        # Allow small rounding tolerance (e.g. 0.1%)
                        if abs(exchange_sl - entry) < (entry * 0.001):
                            state = LONG_BE
                            levels.sl = entry
                        elif abs(exchange_sl - levels.r1_5) < (levels.r1_5 * 0.001):
                            state = LONG_LOCKED
                            levels.sl = levels.r1_5
                else:  # SHORT
                    state = SHORT_ACTIVE
                    if exchange_sl > 0:
                        if abs(exchange_sl - entry) < (entry * 0.001):
                            state = SHORT_BE
                            levels.sl = entry
                        elif abs(exchange_sl - levels.r1_5) < (levels.r1_5 * 0.001):
                            state = SHORT_LOCKED
                            levels.sl = levels.r1_5
                
                trade = Trade(
                    symbol=symbol,
                    direction=direction,
                    entry=entry,
                    qty=size,
                    state=state,
                    levels=levels,
                )
                
                # If no stop loss is set on exchange (e.g., set_stop_loss failed previously), set it now!
                if exchange_sl == 0:
                    logger.info("No SL set on exchange for %s — setting to initial SL %.4f now", symbol, levels.sl)
                    self.exchange.set_stop_loss(symbol, levels.sl)
                
                with self._lock:
                    self._trades[symbol] = trade
                    
                logger.info("Synchronised position for %s | Direction: %s | Entry: %.4f | Qty: %.4f | State: %s",
                            symbol, direction, entry, size, state)
            except Exception as exc:
                logger.error("Failed to sync position for %s: %s", symbol, exc)

    # ── Signal Handler ────────────────────────────────────────────────────────

    def on_signal(self, symbol: str, signal: str, balance: float) -> bool:
        """
        Called when a new ALMA crossover signal fires on a 15-min candle close.
        Returns True if a trade was opened, False otherwise.
        """
        direction = signal  # 'LONG' or 'SHORT'

        # Direction filter
        if self.trade_direction == "LONG"  and direction != "LONG":  return False
        if self.trade_direction == "SHORT" and direction != "SHORT": return False

        with self._lock:
            # Already in a trade on this symbol → skip
            if symbol in self._trades:
                logger.info("Signal %s %s ignored — already in trade", direction, symbol)
                return False

            # Max concurrent trades
            if len(self._trades) >= self.max_trades:
                logger.info("Signal %s %s ignored — max concurrent trades (%d) reached",
                            direction, symbol, self.max_trades)
                return False

        # Fetch symbol info for qty rounding
        sym_info = self.exchange.get_symbol_info(symbol)
        qty_step = sym_info["qty_step"]

        # Get last price as provisional entry (real fill price fetched after)
        provisional_price = self.exchange.get_last_price(symbol)
        if not provisional_price:
            logger.error("Could not get last price for %s", symbol)
            return False

        # Calculate qty
        qty = self.risk_manager.calculate_qty(balance, provisional_price, qty_step)
        if qty < sym_info["min_qty"]:
            logger.warning("Qty %.6f below min %.6f for %s — skipping", qty, sym_info["min_qty"], symbol)
            self.notifier.error(f"Qty too small for {symbol} — check balance/settings")
            return False

        # Place market entry
        order_id = self.exchange.place_market_entry(symbol, direction, qty)
        if not order_id:
            return False

        # Wait for fill and get actual entry price
        fill_price = self.exchange.get_filled_entry_price(symbol, order_id, max_wait=6.0)
        if not fill_price:
            logger.error("Could not confirm fill for %s — proceeding with last price", symbol)
            fill_price = provisional_price

        # Calculate R levels from actual fill price
        levels = self.risk_manager.calculate_levels(fill_price, direction)

        # Place initial stop loss
        self.exchange.set_stop_loss(symbol, levels.sl)

        # Register trade
        trade = Trade(
            symbol=symbol,
            direction=direction,
            entry=fill_price,
            qty=qty,
            state=LONG_ACTIVE if direction == "LONG" else SHORT_ACTIVE,
            levels=levels,
        )
        with self._lock:
            self._trades[symbol] = trade

        # Notify
        if direction == "LONG":
            self.notifier.long_entry(symbol, fill_price, levels.sl, levels.r1_5, levels.r2, levels.r3, qty)
        else:
            self.notifier.short_entry(symbol, fill_price, levels.sl, levels.r1_5, levels.r2, levels.r3, qty)

        self._fire_state_change()
        return True

    # ── Price Update Handler ──────────────────────────────────────────────────

    def on_price_update(self, symbol: str, price: float):
        """Called on every real-time price tick from the WebSocket."""
        with self._lock:
            trade = self._trades.get(symbol)
        if not trade:
            return

        # Update unrealised PnL estimate
        if trade.direction == "LONG":
            trade.pnl = (price - trade.entry) * trade.qty
        else:
            trade.pnl = (trade.entry - price) * trade.qty

        closed = self._check_levels(trade, price)
        if closed:
            self._fire_state_change()

    def _check_levels(self, trade: Trade, price: float) -> bool:
        """
        Advance the state machine based on current price.
        Returns True if the trade was closed (3R hit).
        Thread-safe: caller holds no lock; we acquire it inside as needed.
        """
        lv = trade.levels

        if trade.direction == "LONG":
            # ── 1.5R: move SL to breakeven ───────────────────────────────
            if trade.state == LONG_ACTIVE and price >= lv.r1_5:
                be_price = lv.entry + (lv.r_dist * self.be_offset_r)
                self.exchange.set_stop_loss(trade.symbol, be_price)
                lv.sl = be_price
                with self._lock:
                    trade.state = LONG_BE
                logger.info("%s LONG 1.5R hit -> SL to breakeven with profit offset (%.4f)", trade.symbol, be_price)
                self.notifier.sl_to_be(trade.symbol, "LONG", price)

            # ── 2R: move SL to 1.5R ──────────────────────────────────────
            if trade.state == LONG_BE and price >= lv.r2:
                self.exchange.set_stop_loss(trade.symbol, lv.r1_5)
                lv.sl = lv.r1_5
                with self._lock:
                    trade.state = LONG_LOCKED
                logger.info("%s LONG 2R hit -> SL to 1.5R", trade.symbol)
                self.notifier.sl_to_r1_5(trade.symbol, "LONG", price, lv.r1_5)

            # ── 3R: close trade ───────────────────────────────────────────
            if trade.state == LONG_LOCKED and price >= lv.r3:
                self.exchange.close_position(trade.symbol, "LONG", trade.qty)
                self.notifier.tp_hit(trade.symbol, "LONG", price)
                self._close_trade(trade, outcome="3R WIN", close_price=price)
                return True

        else:  # SHORT
            # ── 1.5R ─────────────────────────────────────────────────────
            if trade.state == SHORT_ACTIVE and price <= lv.r1_5:
                be_price = lv.entry - (lv.r_dist * self.be_offset_r)
                self.exchange.set_stop_loss(trade.symbol, be_price)
                lv.sl = be_price
                with self._lock:
                    trade.state = SHORT_BE
                logger.info("%s SHORT 1.5R hit -> SL to breakeven with profit offset (%.4f)", trade.symbol, be_price)
                self.notifier.sl_to_be(trade.symbol, "SHORT", price)

            # ── 2R ───────────────────────────────────────────────────────
            if trade.state == SHORT_BE and price <= lv.r2:
                self.exchange.set_stop_loss(trade.symbol, lv.r1_5)
                lv.sl = lv.r1_5
                with self._lock:
                    trade.state = SHORT_LOCKED
                logger.info("%s SHORT 2R hit -> SL to 1.5R", trade.symbol)
                self.notifier.sl_to_r1_5(trade.symbol, "SHORT", price, lv.r1_5)

            # ── 3R ───────────────────────────────────────────────────────
            if trade.state == SHORT_LOCKED and price <= lv.r3:
                self.exchange.close_position(trade.symbol, "SHORT", trade.qty)
                self.notifier.tp_hit(trade.symbol, "SHORT", price)
                self._close_trade(trade, outcome="3R WIN", close_price=price)
                return True

        return False

    # ── Position Closed Handler (SL hit detection) ─────────────────────────

    def on_position_closed(self, symbol: str, close_price: float = 0.0):
        """
        Called by the private WebSocket when position size goes to 0.
        Covers SL hits and any other external closure.
        """
        with self._lock:
            trade = self._trades.get(symbol)
        if not trade:
            return  # already removed (e.g. 3R close)

        logger.info("Position closed externally for %s (SL hit or manual)", symbol)
        self.notifier.sl_hit(trade.symbol, trade.direction)
        self._close_trade(trade, outcome="SL", close_price=close_price)
        self._fire_state_change()

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _close_trade(self, trade: Trade, outcome: str, close_price: float):
        """Remove trade from active, add to history."""
        pnl = trade.pnl
        with self._lock:
            self._trades.pop(trade.symbol, None)
            self._history.append({
                "symbol":    trade.symbol,
                "direction": trade.direction,
                "entry":     trade.entry,
                "close":     close_price,
                "qty":       trade.qty,
                "outcome":   outcome,
                "pnl":       round(pnl, 4),
                "duration":  round(time.time() - trade.open_time, 0),
            })
            self._save_history()

    def _fire_state_change(self):
        if self.on_state_change:
            try:
                self.on_state_change()
            except Exception as exc:
                logger.warning("on_state_change callback error: %s", exc)
