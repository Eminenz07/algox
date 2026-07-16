"""
main.py
ALGOX Trading Bot — entry point.
Initialises all components and keeps the process alive.
"""

import json
import logging
import logging.handlers   # must be imported before basicConfig references it
import threading
import time
import sys
import os

# Force UTF-8 on Windows console so arrow/emoji chars don't crash the logger
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            "logs/bot.log", maxBytes=5_000_000, backupCount=3
        ),
    ],
)

logger = logging.getLogger("main")


def load_config(path: str = "config.json") -> dict:
    with open(path, "r") as f:
        cfg = json.load(f)
    
    # Environment variable overrides for secure cloud deployment (e.g. HuggingFace Secrets)
    if os.environ.get("BYBIT_API_KEY"):
        cfg["exchange"]["api_key"] = os.environ["BYBIT_API_KEY"]
    if os.environ.get("BYBIT_API_SECRET"):
        cfg["exchange"]["api_secret"] = os.environ["BYBIT_API_SECRET"]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        cfg["telegram"]["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        cfg["telegram"]["chat_id"] = os.environ["TELEGRAM_CHAT_ID"]
        
    return cfg


def main():
    cfg = load_config()
    logger.info("=" * 60)
    logger.info("  ALGOX Trading Bot starting...")
    logger.info("  Pairs : %s", cfg["trading"]["pairs"])
    logger.info("  TF    : %s min  |  Leverage: %dx  |  Risk: %.1f%%",
                cfg["trading"]["timeframe"],
                cfg["trading"]["leverage"],
                cfg["trading"]["risk_per_trade_pct"])
    logger.info("=" * 60)

    # ── Imports (after logging is ready) ──────────────────────────────────────
    from exchange         import BybitClient
    from risk_manager     import RiskManager
    from trade_manager    import TradeManager
    from bot_engine       import BotEngine
    from notifier         import Notifier
    import dashboard.app  as dashboard

    # ── Initialise components ─────────────────────────────────────────────────
    exc_cfg = cfg["exchange"]
    client  = BybitClient(
        api_key    = exc_cfg["api_key"],
        api_secret = exc_cfg["api_secret"],
        demo       = exc_cfg["demo"],
    )

    notifier = Notifier(
        token   = cfg["telegram"]["bot_token"],
        chat_id = cfg["telegram"]["chat_id"],
    )

    strat_cfg = cfg["strategy"]
    risk_mgr  = RiskManager(
        sl_pct             = strat_cfg["sl_pct"],
        risk_per_trade_pct = cfg["trading"]["risk_per_trade_pct"],
    )

    trade_cfg = cfg["trading"]
    tm = TradeManager(
        exchange        = client,
        risk_manager    = risk_mgr,
        notifier        = notifier,
        max_trades      = trade_cfg["max_concurrent_trades"],
        trade_direction = trade_cfg["trade_direction"],
    )

    # ── Setup exchange for each symbol ────────────────────────────────────────
    symbols   = trade_cfg["pairs"]
    leverage  = trade_cfg["leverage"]
    for sym in symbols:
        client.set_isolated_margin(sym, leverage)
        client.set_leverage(sym, leverage)
        time.sleep(0.3)   # gentle rate limiting

    # ── Synchronise open positions ────────────────────────────────────────────
    tm.sync_positions(symbols)

    # ── Bot engine (polling-based — replaces WebSocket) ─────────────────────────
    engine = BotEngine(
        exchange      = client,
        trade_manager = tm,
        symbols       = symbols,
        config        = cfg,
    )
    engine.start()

    # ── Dashboard ─────────────────────────────────────────────────────────────
    dash_cfg = cfg["dashboard"]
    dashboard.init_dashboard(tm, client, cfg)

    dash_host = os.environ.get("HOST", dash_cfg["host"])
    dash_port = int(os.environ.get("PORT", dash_cfg["port"]))

    dash_thread = threading.Thread(
        target=dashboard.run,
        kwargs={"host": dash_host, "port": dash_port},
        daemon=True,
    )
    dash_thread.start()

    # ── Startup Telegram notification ─────────────────────────────────────────
    balance = client.get_equity()
    notifier.info(
        f"🚀 ALGOX Bot started!\n"
        f"Pairs  : {', '.join(symbols)}\n"
        f"Balance: ${balance:.2f} USDT\n"
        f"Risk   : {trade_cfg['risk_per_trade_pct']}% | Lev: {leverage}x\n"
        f"Dashboard: http://{dash_host}:{dash_port}"
    )

    logger.info("Bot is live. Dashboard -> http://%s:%d", dash_host, dash_port)

    # ── Keep alive ────────────────────────────────────────────────────────────
    try:
        while True:
            time.sleep(30)
            # Heartbeat log every 30 seconds
            active = tm.active_count()
            bal    = client.get_equity()
            logger.info("Heartbeat | Active trades: %d | Equity: $%.2f", active, bal)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        engine.stop()
        notifier.info("🛑 ALGOX Bot stopped by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
