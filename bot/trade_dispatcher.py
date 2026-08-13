import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from exchange import BybitClient
from risk_manager import RiskManager
from security import decrypt_text
from notifier import Notifier
import db_model
import os

logger = logging.getLogger(__name__)

# Thread pool for asynchronous trade execution across multiple users
executor = ThreadPoolExecutor(max_workers=20)

def dispatch_signal(symbol: str, direction: str, entry_price: float, config: dict):
    """
    Called by BotEngine when a signal is generated.
    Queries active users and queues trade execution tasks.
    """
    logger.info("📡 Dispatching %s signal for %s at entry price %.2f", direction, symbol, entry_price)
    
    # Get all active credentials
    conn = db_model.get_connection()
    try:
        with conn.cursor(cursor_factory=db_model.RealDictCursor) as cur:
            cur.execute("""
                SELECT uc.*, u.email, u.username, u.subscription_status
                FROM user_credentials uc
                JOIN users u ON uc.user_id = u.id
                WHERE uc.is_active = TRUE
            """)
            active_users = cur.fetchall()
    except Exception as e:
        logger.error("Failed to fetch active users for dispatch: %s", e)
        return
    finally:
        conn.close()

    logger.info("Found %d active users to execute trade.", len(active_users))
    for user_cred in active_users:
        # Run asynchronously in thread pool
        executor.submit(execute_user_trade, user_cred, symbol, direction, entry_price, config)

def execute_user_trade(user_cred: dict, symbol: str, direction: str, entry_price: float, config: dict):
    """Executes order placement, calculates levels, and registers stops for a single user."""
    email = user_cred["email"]
    user_id = user_cred["user_id"]
    api_key = user_cred["api_key"]
    enc_secret = user_cred["encrypted_api_secret"]
    iv = user_cred["encryption_iv"]
    
    logger.info("Executing trade for user %s (%s)...", user_cred["username"], email)
    
    try:
        # Decrypt secret
        master_key = os.environ.get("ALGOX_ENCRYPTION_KEY")
        if not master_key:
            raise ValueError("ALGOX_ENCRYPTION_KEY environment variable is not set.")
        api_secret = decrypt_text(enc_secret, iv, master_key)
        
        # Instantiate user Bybit client
        client = BybitClient(api_key=api_key, api_secret=api_secret, demo=True)
        
        # Check if already in trade for this symbol
        existing = client.get_position(symbol)
        if existing and float(existing.get("size", 0)) > 0:
            logger.info("User %s already has a position in %s. Skipping.", email, symbol)
            return

        # Setup leverage & isolated margin
        leverage = user_cred.get("leverage") or config["trading"].get("leverage", 10)
        client.set_isolated_margin(symbol, leverage)
        client.set_leverage(symbol, leverage)
        
        # Fetch balance & calculate quantity
        balance = client.get_equity()
        if balance <= 0:
            logger.warning("User %s balance is $0. Cannot place trade.", email)
            return
            
        risk_mode = user_cred.get("risk_mode") or "PERCENT"
        risk_val = user_cred.get("risk_amount") or config["trading"].get("risk_per_trade_pct", 1.0)
        
        if risk_mode == "USD":
            risk_usd = float(risk_val)
        else:
            risk_usd = balance * (float(risk_val) / 100.0)
            
        sl_pct = config["strategy"].get("sl_pct", 0.5)
        r_price = entry_price * (sl_pct / 100.0)
        
        symbol_info = client.get_symbol_info(symbol)
        qty_step = symbol_info["qty_step"]
        
        import math
        raw_qty = risk_usd / r_price
        qty = math.floor(raw_qty / qty_step) * qty_step
        qty = round(qty, 8)
        
        if qty <= 0:
            logger.warning("User %s calculated quantity is 0 (balance or risk amount too small?). Skipping.", email)
            return
            
        # Place Market Entry
        order_id = client.place_market_entry(symbol, direction, qty)
        if not order_id:
            logger.error("User %s entry order failed.", email)
            return
            
        # Get actual fill price
        fill_price = client.get_filled_entry_price(symbol, order_id)
        if not fill_price:
            fill_price = entry_price  # fallback
            
        # Calculate stops
        risk_mgr = RiskManager(sl_pct=sl_pct, risk_per_trade_pct=1.0)  # dummy risk pct for levels calculation
        levels = risk_mgr.calculate_levels(fill_price, direction)
        
        # Place TP and SL directly on Bybit Futures
        tp_price = levels.r1
        sl_price = levels.sl
        
        stops_set = client.set_trading_stops(symbol, sl_price, tp_price)
        if not stops_set:
            logger.warning("Failed to set stops on exchange for user %s. Closing position for safety.", email)
            client.close_position(symbol, direction, qty)
            return
            
        # Save open trade to Postgres
        # We save exit_price as 0.0, outcome as 'OPEN', pnl as 0.0 initially
        db_model.log_trade(
            user_id=user_id,
            symbol=symbol,
            direction=direction,
            entry_price=fill_price,
            close_price=0.0,
            qty=qty,
            pnl=0.0,
            outcome="OPEN"
        )
        
        # Notify user (we can fetch their TG settings or default to global notifier)
        # For simplicity, we send to the system Telegram channel
        token = config["telegram"]["bot_token"]
        chat_id = config["telegram"]["chat_id"]
        notifier = Notifier(token=token, chat_id=chat_id)
        notifier.long_entry(symbol, fill_price, sl_price, tp_price, qty) if direction == "LONG" else notifier.short_entry(symbol, fill_price, sl_price, tp_price, qty)
        
        logger.info("Trade successfully opened & registered for user %s.", email)
        
    except Exception as e:
        logger.error("Exception during trade execution for user %s: %s", email, e)

def track_active_positions(config: dict):
    """
    Called periodically by BotEngine.
    Checks all open trades in the database and updates them if they have closed on Bybit.
    """
    conn = db_model.get_connection()
    try:
        with conn.cursor(cursor_factory=db_model.RealDictCursor) as cur:
            # Get all open trades
            cur.execute("""
                SELECT t.id as trade_id, t.symbol, t.direction, t.qty, t.user_id, t.entry_price,
                       uc.api_key, uc.encrypted_api_secret, uc.encryption_iv,
                       u.email
                FROM trades t
                JOIN user_credentials uc ON t.user_id = uc.user_id
                JOIN users u ON t.user_id = u.id
                WHERE t.outcome = 'OPEN'
            """)
            open_trades = cur.fetchall()
    except Exception as e:
        logger.error("Failed to query open trades from database: %s", e)
        return
    finally:
        conn.close()

    if not open_trades:
        return

    master_key = os.environ.get("ALGOX_ENCRYPTION_KEY")
    for trade in open_trades:
        trade_id = trade["trade_id"]
        symbol = trade["symbol"]
        direction = trade["direction"]
        qty = trade["qty"]
        user_id = trade["user_id"]
        entry_price = trade["entry_price"]
        api_key = trade["api_key"]
        enc_secret = trade["encrypted_api_secret"]
        iv = trade["encryption_iv"]
        email = trade["email"]
        
        try:
            api_secret = decrypt_text(enc_secret, iv, master_key)
            client = BybitClient(api_key=api_key, api_secret=api_secret, demo=True)
            
            # Check position size
            pos = client.get_position(symbol)
            if not pos or float(pos.get("size", 0)) == 0:
                logger.info("Open trade ID %d for %s has closed on exchange. Syncing...", trade_id, email)
                
                # Fetch recent closed PnL
                resp = client.session.get_closed_pnl(category="linear", symbol=symbol, limit=1)
                records = resp.get("result", {}).get("list", [])
                
                exit_price = 0.0
                pnl = 0.0
                outcome = "SL"
                
                if records:
                    rec = records[0]
                    rec_entry = float(rec["avgEntryPrice"])
                    if abs(rec_entry - entry_price) < (entry_price * 0.005):  # allow 0.5% price difference for slippage/averaging
                        exit_price = float(rec["avgExitPrice"])
                        pnl = float(rec["closedPnl"])
                        outcome = "1R WIN" if pnl > 0 else "SL"
                    else:
                        logger.info("Closed PnL entry price %.2f does not match DB trade entry price %.2f. Waiting for exchange API sync...", rec_entry, entry_price)
                        continue
                else:
                    # Stale history / API lag: skip database update and retry on next poll
                    logger.info("No closed PnL records found on Bybit. Waiting for exchange API sync...")
                    continue
                
                # Update database record
                conn = db_model.get_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE trades 
                            SET close_price = %s, pnl = %s, outcome = %s, closed_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """, (exit_price, pnl, outcome, trade_id))
                    conn.commit()
                except Exception as db_err:
                    conn.rollback()
                    logger.error("Failed to update closed trade in DB: %s", db_err)
                finally:
                    conn.close()

                # Send Telegram alert
                token = config["telegram"]["bot_token"]
                chat_id = config["telegram"]["chat_id"]
                notifier = Notifier(token=token, chat_id=chat_id)
                if outcome == "1R WIN":
                    notifier.tp_hit(symbol, direction, exit_price, pnl)
                else:
                    notifier.sl_hit(symbol, direction, exit_price, pnl)
                    
        except Exception as e:
            logger.error("Error tracking position for user %s: %s", email, e)
