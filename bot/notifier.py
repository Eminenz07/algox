"""
notifier.py
Telegram alert system for the ALGOX trading bot.
Uses plain HTTP requests — no external bot library needed.
"""

import logging
import requests

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id
        self._url    = f"https://api.telegram.org/bot{token}/sendMessage"

    def send(self, message: str) -> bool:
        """Send a Telegram message. Returns True on success."""
        try:
            resp = requests.post(
                self._url,
                json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            if not resp.ok:
                logger.warning("Telegram send failed: %s", resp.text)
            return resp.ok
        except Exception as exc:
            logger.error("Telegram error: %s", exc)
            return False

    # ── Convenience helpers ───────────────────────────────────────────────────

    def long_entry(self, symbol: str, entry: float, sl: float,
                   r1_5: float, r2: float, r3: float, qty: float):
        self.send(
            f"🟢 <b>LONG ENTRY</b>\n"
            f"Symbol : <b>{symbol}</b>\n"
            f"Entry  : {entry:.4f}\n"
            f"SL     : {sl:.4f}\n"
            f"1.5R   : {r1_5:.4f}\n"
            f"2R     : {r2:.4f}\n"
            f"3R (TP): {r3:.4f}\n"
            f"Qty    : {qty}"
        )

    def short_entry(self, symbol: str, entry: float, sl: float,
                    r1_5: float, r2: float, r3: float, qty: float):
        self.send(
            f"🔴 <b>SHORT ENTRY</b>\n"
            f"Symbol : <b>{symbol}</b>\n"
            f"Entry  : {entry:.4f}\n"
            f"SL     : {sl:.4f}\n"
            f"1.5R   : {r1_5:.4f}\n"
            f"2R     : {r2:.4f}\n"
            f"3R (TP): {r3:.4f}\n"
            f"Qty    : {qty}"
        )

    def sl_to_be(self, symbol: str, direction: str, price: float):
        self.send(
            f"⚡ <b>1.5R HIT — SL → Breakeven</b>\n"
            f"{symbol} {direction}\n"
            f"Price: {price:.4f} | New SL: Breakeven"
        )

    def sl_to_r1_5(self, symbol: str, direction: str, price: float, new_sl: float):
        self.send(
            f"⚡ <b>2R HIT — SL → 1.5R</b>\n"
            f"{symbol} {direction}\n"
            f"Price: {price:.4f} | New SL: {new_sl:.4f}"
        )

    def tp_hit(self, symbol: str, direction: str, price: float):
        self.send(
            f"🎯 <b>3R HIT — FULL TP!</b>\n"
            f"{symbol} {direction}\n"
            f"Closed at: {price:.4f} ✅"
        )

    def sl_hit(self, symbol: str, direction: str):
        self.send(f"❌ <b>SL HIT</b>\n{symbol} {direction} position closed by stop loss.")

    def info(self, message: str):
        self.send(f"ℹ️ {message}")

    def error(self, message: str):
        self.send(f"🚨 <b>ERROR</b>\n{message}")
