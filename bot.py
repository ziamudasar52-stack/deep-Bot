#!/usr/bin/env python3
"""
STOCK SCANNER BOT - RAILWAY WORKER VERSION
Deploy as Background Worker on Railway
"""

import os
import time
import requests
import schedule
import json
from datetime import datetime
import pytz
import logging
import sys
from typing import Dict, List, Optional
import traceback

# ========== SETUP LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/stock_bot.log')
    ]
)
logger = logging.getLogger(__name__)

# ========== CONFIGURATION ==========
MBOUM_API_KEY = os.getenv('MBOUM_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Log startup info
logger.info("=" * 60)
logger.info("🚀 STOCK BOT STARTING ON RAILWAY")
logger.info(f"Time: {datetime.now()}")
logger.info("=" * 60)

# Validate
if not MBOUM_API_KEY:
    logger.error("❌ MBOUM_API_KEY missing!")
    sys.exit(1)
if not TELEGRAM_BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN missing!")
if not TELEGRAM_CHAT_ID:
    logger.error("❌ TELEGRAM_CHAT_ID missing!")

# API Settings
BASE_URL = "https://api.mboum.com"
HEADERS = {'Authorization': f'Bearer {MBOUM_API_KEY}'}

# Timezone
TIMEZONE = pytz.timezone('America/New_York')

# Scanning Intervals (optimized for 50k requests/month)
SCAN_INTERVAL = 30  # seconds (optimized)
UNUSUAL_OPTIONS_INTERVAL = 180  # 3 minutes (optimized)
TOP10_INTERVAL = 300  # 5 minutes

# Alert Thresholds
BID_MATCH_PRICE_1 = 199999
BID_MATCH_SHARES_1 = 100
BID_MATCH_PRICE_2 = 2000
BID_MATCH_SHARES_2 = 20
MIN_PERCENT_MOVE = 5
MIN_INSIDER_SHARES = 10000

# ========== API CLIENT ==========
class MboumAPI:
    """MBOUM API client with request tracking"""
    
    request_count = 0
    
    @classmethod
    def make_request(cls, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make API request with error handling"""
        url = f"{BASE_URL}{endpoint}"
        cls.request_count += 1
        
        try:
            logger.debug(f"API Request #{cls.request_count}: {endpoint}")
            response = requests.get(url, headers=HEADERS, params=params, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                logger.error("❌ API Error 401: Invalid API Key")
            elif response.status_code == 429:
                logger.warning("⚠️ API Rate Limit Approaching")
            else:
                logger.error(f"API Error {response.status_code}: {response.text[:200]}")
                
        except requests.exceptions.Timeout:
            logger.error("⏰ API Timeout")
        except Exception as e:
            logger.error(f"API Exception: {str(e)}")
            
        return None
    
    @classmethod
    def get_top_movers(cls, limit: int = 50) -> List[dict]:
        """Get top moving stocks"""
        data = cls.make_request("/v1/markets/movers", {"type": "STOCKS"})
        if data and isinstance(data, list):
            return data[:limit]
        return []
    
    @classmethod
    def get_real_time_quote(cls, symbol: str) -> Optional[dict]:
        """Get real-time quote"""
        return cls.make_request("/v1/markets/quote", {"ticker": symbol, "type": "STOCKS"})
    
    @classmethod
    def get_unusual_options(cls) -> List[dict]:
        """Get unusual options activity"""
        data = cls.make_request("/v1/unusual-options-activity", {
            "type": "STOCKS", 
            "page": 1, 
            "limit": 10
        })
        return data if data else []
    
    @classmethod
    def get_insider_trades(cls, symbol: str = None) -> List[dict]:
        """Get insider trades"""
        params = {"page": 1, "limit": 20}
        if symbol:
            params["ticker"] = symbol
        data = cls.make_request("/v1/insider-trades", params)
        return data if data else []
    
    @classmethod
    def get_market_info(cls) -> Optional[dict]:
        """Get market status"""
        return cls.make_request("/v2/market-info")

# ========== TELEGRAM BOT ==========
class TelegramBot:
    """Telegram messaging"""
    
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        
    def send_message(self, text: str, alert_type: str = "INFO"):
        """Send message to Telegram"""
        if not self.token or not self.chat_id:
            logger.warning(f"Would send Telegram: {alert_type} - {text[:50]}...")
            return False
            
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"📤 Telegram sent: {alert_type}")
                return True
            else:
                logger.error(f"Telegram error: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Telegram exception: {str(e)}")
            return False

# ========== ALERT DETECTOR ==========
class AlertDetector:
    """Detect alerts based on your logic"""
    
    def __init__(self):
        self.alert_history = {}
        self.watchlist = set()
        
    def check_bid_match(self, quote_data: dict) -> bool:
        """Check for bid match patterns"""
        try:
            bid_price = float(quote_data.get('bid', 0))
            bid_size = int(quote_data.get('bidSize', 0))
            
            # Exact match: $199,999 with 100 shares
            if bid_price == BID_MATCH_PRICE_1 and bid_size == BID_MATCH_SHARES_1:
                return True
            
            # High value match: $2,000+ with 20+ shares
            if bid_price >= BID_MATCH_PRICE_2 and bid_size >= BID_MATCH_SHARES_2:
                return True
                
        except (ValueError, TypeError):
            pass
            
        return False
    
    def should_alert(self, symbol: str, alert_type: str, cooldown_minutes: int = 5) -> bool:
        """Prevent duplicate alerts"""
        key = f"{symbol}_{alert_type}"
        now = time.time()
        
        if key in self.alert_history:
            last_time = self.alert_history[key]
            if now - last_time < cooldown_minutes * 60:
                return False
        
        self.alert_history[key] = now
        return True

# ========== MAIN BOT ==========
class StockScannerBot:
    """Main bot class"""
    
    def __init__(self):
        self.api = MboumAPI
        self.telegram = TelegramBot()
        self.detector = AlertDetector()
        self.market_open = False
        self.startup_sent = False
        
    def check_market_hours(self) -> bool:
        """Check if market is open (6 AM - 6 PM EST, Mon-Fri)"""
        try:
            now_est = datetime.now(TIMEZONE)
            
            # Check weekend
            if now_est.weekday() >= 5:  # Saturday=5, Sunday=6
                return False
            
            # Check time (6 AM - 6 PM EST)
            current_hour = now_est.hour
            if 6 <= current_hour < 18:
                return True
                
        except Exception as e:
            logger.error(f"Time check error: {e}")
            
        return False
    
    def send_startup_message(self):
        """Send startup message at 6 AM"""
        if not self.startup_sent and self.market_open:
            message = "✅ Good Morning! It's 6 AM EST\nStock Bot is running now!"
            self.telegram.send_message(message, "STARTUP")
            self.startup_sent = True
            logger.info("Startup message sent")
    
    def scan_top_movers(self):
        """Scan top 50 movers"""
        if not self.market_open:
            return
            
        logger.info("🔍 Scanning top 50 movers...")
        movers = self.api.get_top_movers(50)
        
        if not movers:
            logger.warning("No movers data received")
            return
            
        # Process each mover
        for stock in movers[:30]:  # Limit to 30 for efficiency
            try:
                symbol = stock.get('symbol') or stock.get('ticker')
                change_percent = float(stock.get('changePercent', 0))
                
                if not symbol or change_percent < MIN_PERCENT_MOVE:
                    continue
                    
                logger.info(f"📈 {symbol}: +{change_percent:.1f}% - Processing...")
                
                # Get real-time quote for bid/ask check
                quote = self.api.get_real_time_quote(symbol)
                if quote and self.detector.check_bid_match(quote):
                    if self.detector.should_alert(symbol, "BID_MATCH"):
                        self.send_bid_match_alert(symbol, quote, change_percent)
                        
                        # Check halt status
                        self.check_halt_status(symbol)
                        
                        # Add to watchlist
                        self.detector.watchlist.add(symbol)
                else:
                    # No bid match, check insider trades
                    self.check_insider_activity(symbol, change_percent)
                    
            except Exception as e:
                logger.error(f"Error processing {stock.get('symbol')}: {e}")
    
    def check_insider_activity(self, symbol: str, change_percent: float):
        """Check for large insider trades"""
        if change_percent < MIN_PERCENT_MOVE:
            return
            
        insider_trades = self.api.get_insider_trades(symbol)
        for trade in insider_trades:
            shares = int(trade.get('shares', 0))
            if shares >= MIN_INSIDER_SHARES:
                if self.detector.should_alert(symbol, "INSIDER_TRADE"):
                    self.send_insider_alert(symbol, trade, change_percent)
                break
    
    def check_halt_status(self, symbol: str):
        """Check if stock is halted"""
        market_info = self.api.get_market_info()
        if market_info and market_info.get('halted'):
            if self.detector.should_alert(symbol, "HALT"):
                self.send_halt_alert(symbol)
    
    def scan_unusual_options(self):
        """Scan unusual options activity"""
        if not self.market_open:
            return
            
        logger.info("🎯 Scanning unusual options...")
        options_data = self.api.get_unusual_options()
        
        for option in options_data:
            symbol = option.get('symbol')
            if symbol and self.detector.should_alert(symbol, "UNUSUAL_OPTIONS"):
                self.send_unusual_options_alert(option)
    
    def send_top10_report(self):
        """Send top 10 gainers report"""
        if not self.market_open:
            return
            
        logger.info("🏆 Sending top 10 report...")
        movers = self.api.get_top_movers(10)
        
        if not movers:
            return
            
        now_est = datetime.now(TIMEZONE).strftime("%I:%M %p EST")
        message = f"<b>🏆 TOP 10 GAINERS ({now_est})</b>\n\n"
        
        for i, stock in enumerate(movers[:10], 1):
            symbol = stock.get('symbol') or stock.get('ticker')
            price = float(stock.get('price', 0))
            change = float(stock.get('changePercent', 0))
            
            if symbol:
                message += f"{i}. <b>{symbol}</b>: ${price:.2f} (+{change:.1f}%)\n"
        
        self.telegram.send_message(message, "TOP10")
    
    # ========== ALERT MESSAGES ==========
    def send_bid_match_alert(self, symbol: str, quote: dict, change_percent: float):
        """Send bid match alert"""
        bid_price = float(quote.get('bid', 0))
        bid_size = int(quote.get('bidSize', 0))
        total_value = bid_price * bid_size
        
        message = (
            f"<b>⚡ BID MATCH ALERT</b>\n"
            f"Stock: <b>{symbol}</b>\n"
            f"Price: ${quote.get('price', 0):.2f} (+{change_percent:.1f}%)\n"
            f"Bid: {bid_size} shares @ ${bid_price:,.2f}\n"
            f"Total Value: ${total_value:,.2f}\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        self.telegram.send_message(message, "BID_MATCH")
    
    def send_insider_alert(self, symbol: str, trade: dict, change_percent: float):
        """Send insider trade alert"""
        shares = int(trade.get('shares', 0))
        price = float(trade.get('price', 0))
        total = shares * price
        
        message = (
            f"<b>🚨 UNUSUAL ACTIVITY</b>\n"
            f"Stock: <b>{symbol}</b>\n"
            f"Price: ${price:.2f} (+{change_percent:.1f}%)\n"
            f"Insider: {trade.get('insider', 'N/A')}\n"
            f"Transaction: {shares:,} shares @ ${price:.2f}\n"
            f"Total Value: ${total:,.2f}\n"
            f"Note: Stock up {change_percent:.1f}% with large insider trade"
        )
        self.telegram.send_message(message, "INSIDER_TRADE")
    
    def send_unusual_options_alert(self, option: dict):
        """Send unusual options alert"""
        message = (
            f"<b>🎯 UNUSUAL OPTIONS</b>\n"
            f"Stock: <b>{option.get('symbol')}</b>\n"
            f"Contract: {option.get('contractType')} ${option.get('strike')}\n"
            f"Expiry: {option.get('expiration')}\n"
            f"Volume: {option.get('volume', 0):,} contracts\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        self.telegram.send_message(message, "UNUSUAL_OPTIONS")
    
    def send_halt_alert(self, symbol: str):
        """Send halt alert"""
        message = (
            f"<b>⏸️ HALT ALERT</b>\n"
            f"Stock: <b>{symbol}</b>\n"
            f"Status: TRADING HALTED\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}\n"
            f"Note: Had bid match earlier"
        )
        self.telegram.send_message(message, "HALT")
    
    def setup_schedule(self):
        """Setup scheduled tasks"""
        # Main scanner every 30 seconds
        schedule.every(SCAN_INTERVAL).seconds.do(self.scan_top_movers)
        
        # Unusual options every 3 minutes
        schedule.every(UNUSUAL_OPTIONS_INTERVAL).seconds.do(self.scan_unusual_options)
        
        # Top 10 report every 5 minutes
        schedule.every(TOP10_INTERVAL).seconds.do(self.send_top10_report)
        
        # Market status check every minute
        schedule.every(60).seconds.do(self.check_market_status)
        
        logger.info(f"Scheduled tasks setup:")
        logger.info(f"  - Main scan: every {SCAN_INTERVAL}s")
        logger.info(f"  - Options scan: every {UNUSUAL_OPTIONS_INTERVAL}s")
        logger.info(f"  - Top 10 report: every {TOP10_INTERVAL}s")
    
    def check_market_status(self):
        """Check and update market status"""
        was_open = self.market_open
        self.market_open = self.check_market_hours()
        
        if not was_open and self.market_open:
            logger.info("✅ Market is now OPEN (6 AM - 6 PM EST)")
            self.send_startup_message()
        elif was_open and not self.market_open:
            logger.info("⏸️ Market is now CLOSED")
            self.startup_sent = False
    
    def run(self):
        """Main bot loop"""
        logger.info("🚀 Starting Stock Scanner Bot...")
        
        # Send test message
        self.telegram.send_message(
            "🤖 Stock Bot Started on Railway\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%Y-%m-%d %I:%M %p EST')}\n"
            "Waiting for market hours (6 AM - 6 PM EST)",
            "STARTUP"
        )
        
        # Setup schedule
        self.setup_schedule()
        
        # Initial market check
        self.check_market_status()
        
        # Main loop
        logger.info("🔄 Entering main loop...")
        try:
            while True:
                if self.market_open:
                    schedule.run_pending()
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("👋 Bot stopped by user")
        except Exception as e:
            logger.error(f"💥 Critical error: {e}")
            logger.error(traceback.format_exc())
            self.telegram.send_message(
                f"❌ Bot crashed:\n{str(e)[:200]}",
                "ERROR"
            )

# ========== MAIN ENTRY ==========
if __name__ == "__main__":
    try:
        bot = StockScannerBot()
        bot.run()
    except Exception as e:
        logger.error(f"💥 Failed to start bot: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
