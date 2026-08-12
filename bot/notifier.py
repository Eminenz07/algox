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

    def long_entry(self, symbol: str, entry: float, sl: float, tp: float, qty: float):
        self.send(
            f"🟢 <b>{symbol} — LONG ENTRY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Position Size:</b> {qty:.4f} BTC\n"
            f"💰 <b>Entry Price:</b> {entry:.2f} USDT\n"
            f"🎯 <b>Take Profit (1R):</b> {tp:.2f} USDT\n"
            f"🛡️ <b>Stop Loss (-1R):</b> {sl:.2f} USDT\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <i>ALGOX 1:1 R:R Strategy</i>"
        )

    def short_entry(self, symbol: str, entry: float, sl: float, tp: float, qty: float):
        self.send(
            f"🔴 <b>{symbol} — SHORT ENTRY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Position Size:</b> {qty:.4f} BTC\n"
            f"💰 <b>Entry Price:</b> {entry:.2f} USDT\n"
            f"🎯 <b>Take Profit (1R):</b> {tp:.2f} USDT\n"
            f"🛡️ <b>Stop Loss (-1R):</b> {sl:.2f} USDT\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <i>ALGOX 1:1 R:R Strategy</i>"
        )

    def tp_hit(self, symbol: str, direction: str, price: float, pnl: float = 0.0):
        self.send(
            f"🎉 <b>{symbol} — TAKE PROFIT HIT!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Outcome:</b> 1R WIN ✅\n"
            f"💰 <b>Exit Price:</b> {price:.2f} USDT\n"
            f"📈 <b>Trade PnL:</b> +{pnl:.2f} USDT\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <i>ALGOX 1:1 R:R Strategy</i>"
        )

    def sl_hit(self, symbol: str, direction: str, price: float, pnl: float = 0.0):
        self.send(
            f"❌ <b>{symbol} — STOP LOSS HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📉 <b>Outcome:</b> Full Loss (1R) 🔴\n"
            f"💰 <b>Exit Price:</b> {price:.2f} USDT\n"
            f"📉 <b>Trade PnL:</b> {pnl:.2f} USDT\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <i>ALGOX 1:1 R:R Strategy</i>"
        )

    def info(self, message: str):
        self.send(f"ℹ️ {message}")

    def error(self, message: str):
        self.send(f"🚨 <b>ERROR</b>\n{message}")
