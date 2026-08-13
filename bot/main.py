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


def load_env():
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key] = val

def load_config(path: str = "config.json") -> dict:
    with open(path, "r") as f:
        cfg = json.load(f)
    
    # Environment variable overrides
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
    load_env()
    cfg = load_config()
    
    logger.info("=" * 60)
    logger.info("  ALGOX Multi-Tenant SaaS Bot starting...")
    logger.info("  Pairs : %s", cfg["trading"]["pairs"])
    logger.info("  TF    : %s min  |  Leverage: %dx",
                cfg["trading"]["timeframe"],
                cfg["trading"]["leverage"])
    logger.info("=" * 60)

    # ── Database Initialization ───────────────────────────────────────────────
    import db_model
    conn_str = os.environ.get("DATABASE_URL")
    admin_email = os.environ.get("ADMIN_EMAIL", "emmyadeoluwa@gmail.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Emmy1282")
    admin_username = os.environ.get("ADMIN_USERNAME", "His_Emi")
    
    if not conn_str:
        logger.error("DATABASE_URL environment variable is missing!")
        sys.exit(1)
        
    db_model.init_db(conn_str, admin_email, admin_password, admin_username)

    # ── Imports ───────────────────────────────────────────────────────────────
    from exchange         import BybitClient
    from bot_engine       import BotEngine
    from notifier         import Notifier
    import dashboard.app  as dashboard

    # Create public client for candle fetching (no API keys required for public kline data)
    public_client = BybitClient(api_key="", api_secret="", demo=True)

    notifier = Notifier(
        token   = cfg["telegram"]["bot_token"],
        chat_id = cfg["telegram"]["chat_id"],
    )

    # ── Bot Engine (Global Candle Indicators Tracker) ─────────────────────────
    symbols = cfg["trading"]["pairs"]
    engine = BotEngine(
        exchange      = public_client,
        trade_manager = None,  # TM is deprecated in multi-tenant model
        symbols       = symbols,
        config        = cfg,
    )
    engine.start()

    # ── Dashboard Server ──────────────────────────────────────────────────────
    dashboard.init_dashboard(cfg)

    dash_host = os.environ.get("HOST", "0.0.0.0")
    dash_port = int(os.environ.get("PORT", cfg["dashboard"]["port"]))

    dash_thread = threading.Thread(
        target=dashboard.run,
        kwargs={"host": dash_host, "port": dash_port},
        daemon=True,
    )
    dash_thread.start()

    notifier.info(
        f"🚀 ALGOX Multi-Tenant SaaS Bot started!\n"
        f"Database connected successfully ✅\n"
        f"Dashboard: http://{dash_host}:{dash_port}"
    )

    logger.info("Bot is live. Dashboard -> http://%s:%d", dash_host, dash_port)

    # ── Keep alive loop ───────────────────────────────────────────────────────
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        engine.stop()
        notifier.info("🛑 ALGOX SaaS Bot stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
