#!/usr/bin/env python3
"""
STOCK SCANNER BOT - Complete Working Version
Deploy on Railway as Background Worker
"""

import os
import time
import requests
import schedule
import json
from datetime import datetime, timedelta
import pytz
from typing import Dict, List, Optional, Set
import logging
from dataclasses import dataclass
import sys

# ========== CONFIGURATION ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
MBOUM_API_KEY = os.getenv('MBOUM_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# API Configuration
BASE_URL = "https://api.mboum.com"

# Bot Configuration
TIMEZONE = pytz.timezone('America/New_York')

# Alert Thresholds
BID_MATCH_PRICE_1 = 199999
BID_MATCH_SHARES_1 = 100
BID_MATCH_PRICE_2 = 2000
BID_MATCH_SHARES_2 = 20
MIN_PERCENT_MOVE = 5
MIN_INSIDER_SHARES = 10000

# Volume multipliers based on % move
VOLUME_MULTIPLIERS = {
    (1, 10): 10,      # 1-10% move: 10x volume
    (10, 50): 20,     # 10-50% move: 20x volume
    (50, 100): 30,    # 50-100% move: 30x volume
    (100, 200): 50,   # 100-200% move: 50x volume
    (200, float('inf')): 100  # 200%+ move: 100x volume
}

# ========== DATA CLASSES ==========
@dataclass
class StockData:
    symbol: str
    price: float
    change_percent: float
    volume: int
    bid: float = 0.0
    bid_size: int = 0
    ask: float = 0.0
    ask_size: int = 0
    previous_close: float = 0.0

# ========== API FUNCTIONS ==========
def make_api_call(endpoint: str, params: Dict = None) -> Optional[Dict]:
    """Make API call to MBOUM"""
    if not MBOUM_API_KEY:
        logger.error("❌ MBOUM_API_KEY not set")
        return None
    
    url = f"{BASE_URL}{endpoint}"
    headers = {'Authorization': MBOUM_API_KEY}
    
    try:
        logger.debug(f"API Call: {endpoint}")
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"API Exception: {str(e)}")
        return None

def get_top_gainers(limit: int = 50) -> List[StockData]:
    """Get top gainers using screener endpoint"""
    logger.info(f"📈 Getting top {limit} gainers...")
    
    params = {
        'metricType': 'overview',
        'filter': 'day_gainers',
        'page': '1',
        'limit': str(limit)
    }
    
    data = make_api_call("/v1/screener", params)
    
    if not data or 'body' not in data:
        logger.warning("❌ No data from screener")
        return []
    
    stocks = []
    
    for item in data['body'][:limit]:
        try:
            # Extract data from screener response
            symbol = item.get('symbol', '')
            
            # Get price and change
            price = item.get('regularMarketPrice', 0)
            change_percent = item.get('regularMarketChangePercent', 0)
            volume = item.get('regularMarketVolume', 0)
            bid = item.get('bid', 0)
            bid_size = item.get('bidSize', 0)
            ask = item.get('ask', 0)
            ask_size = item.get('askSize', 0)
            prev_close = item.get('regularMarketPreviousClose', 0)
            
            if not symbol:
                continue
            
            stock = StockData(
                symbol=str(symbol),
                price=float(price),
                change_percent=float(change_percent),
                volume=int(volume),
                bid=float(bid),
                bid_size=int(bid_size),
                ask=float(ask),
                ask_size=int(ask_size),
                previous_close=float(prev_close)
            )
            stocks.append(stock)
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing {item.get('symbol', 'unknown')}: {e}")
            continue
    
    # Sort by percentage change (highest first)
    stocks.sort(key=lambda x: x.change_percent, reverse=True)
    logger.info(f"✅ Got {len(stocks)} gainers")
    return stocks

def get_unusual_options() -> List[Dict]:
    """Get unusual options activity"""
    logger.info("🎯 Getting unusual options...")
    
    data = make_api_call("/v1/markets/options/unusual-options-activity", {
        'type': 'STOCKS',
        'page': '1'
    })
    
    if data and 'body' in data:
        logger.info(f"✅ Found {len(data['body'])} unusual options")
        return data['body']
    return []

def get_insider_trades(symbol: str = None) -> List[Dict]:
    """Get insider trades"""
    params = {'page': '1', 'limit': '20'}
    if symbol:
        params['ticker'] = symbol
    
    data = make_api_call("/v1/insider-trades", params)
    
    if data and 'body' in data:
        return data['body']
    return []

# ========== TELEGRAM FUNCTIONS ==========
def send_telegram_message(message: str, alert_type: str = "INFO") -> bool:
    """Send message to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(f"Telegram not configured: {message[:50]}...")
        return False
    
    try:
        # Add emoji based on alert type
        emojis = {
            "STARTUP": "☀️",
            "BID_MATCH": "⚡",
            "VOLUME_SPIKE": "📊",
            "UNUSUAL_ACTIVITY": "🚨",
            "UNUSUAL_OPTIONS": "🎯",
            "HALT_ALERT": "⏸️",
            "LARGE_SALE": "📉",
            "TOP10": "🏆",
            "DEBUG": "🔧"
        }
        
        emoji = emojis.get(alert_type, "ℹ️")
        formatted_msg = f"{emoji} {message}"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': formatted_msg,
            'parse_mode': 'HTML'
        }
        
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            logger.info(f"📤 Telegram sent: {alert_type}")
            return True
        else:
            logger.error(f"Telegram error: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Telegram exception: {str(e)}")
        return False

# ========== ALERT DETECTION ==========
class AlertDetector:
    def __init__(self):
        self.alert_history = {}  # symbol_alerttype -> timestamp
        self.watchlist = set()   # Symbols to monitor for sales
        self.volume_cache = {}   # symbol -> (timestamp, avg_volume)
        self.processed_5min = set()  # Prevent duplicate 5-min lists
    
    def check_bid_match(self, stock: StockData) -> bool:
        """Check for bid match patterns"""
        # Pattern 1: $199,999 with exactly 100 shares
        if stock.bid == BID_MATCH_PRICE_1 and stock.bid_size == BID_MATCH_SHARES_1:
            logger.info(f"🎯 EXACT BID MATCH: {stock.symbol} - ${stock.bid} with {stock.bid_size} shares")
            return True
        
        # Pattern 2: $2,000+ with 20+ shares
        elif stock.bid >= BID_MATCH_PRICE_2 and stock.bid_size >= BID_MATCH_SHARES_2:
            logger.info(f"🎯 HIGH VALUE BID: {stock.symbol} - ${stock.bid} with {stock.bid_size} shares")
            return True
        
        return False
    
    def check_volume_spike(self, symbol: str, current_volume: int, percent_change: float) -> bool:
        """Check for volume spike using smart thresholds"""
        # Get or calculate average volume
        if symbol not in self.volume_cache:
            # Default average for new stocks
            self.volume_cache[symbol] = (datetime.now(), 10000)
            return False
        
        _, avg_volume = self.volume_cache[symbol]
        
        # Get multiplier based on % move
        multiplier = 10  # default
        for (min_p, max_p), mult in VOLUME_MULTIPLIERS.items():
            if min_p <= abs(percent_change) < max_p:
                multiplier = mult
                break
        
        # Check spike
        if avg_volume > 0 and current_volume > (avg_volume * multiplier):
            logger.info(f"📊 VOLUME SPIKE: {symbol} - {current_volume:,} vs avg {avg_volume:,} ({multiplier}x)")
            return True
        
        return False
    
    def can_send_alert(self, symbol: str, alert_type: str) -> bool:
        """Prevent duplicate alerts within 5 minutes"""
        key = f"{symbol}_{alert_type}"
        now = datetime.now()
        
        if key in self.alert_history:
            last_alert = self.alert_history[key]
            if (now - last_alert).total_seconds() < 300:  # 5 minutes
                return False
        
        self.alert_history[key] = now
        return True

# ========== MAIN BOT CLASS ==========
class StockScannerBot:
    def __init__(self):
        self.detector = AlertDetector()
        self.is_running = False
        self.market_open = False
        self.startup_sent = False
        
    def check_market_hours(self) -> bool:
        """Check if within market hours (6 AM - 6 PM EST, Mon-Fri)"""
        now_est = datetime.now(TIMEZONE)
        
        # Check weekend
        if now_est.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        
        # Check time (6 AM - 6 PM EST)
        if 6 <= now_est.hour < 18:
            return True
        
        return False
    
    def startup_sequence(self):
        """Run at 6 AM EST"""
        if not self.startup_sent and self.market_open:
            send_telegram_message(
                "Good Morning its 6am Bot is running now",
                "STARTUP"
            )
            self.startup_sent = True
            logger.info("✅ Startup message sent")
    
    def scan_top_gainers(self):
        """Main scanner - runs every 10 seconds"""
        if not self.market_open:
            return
        
        logger.info("🔍 Scanning top gainers...")
        stocks = get_top_gainers(50)
        
        if not stocks:
            return
        
        for stock in stocks:
            # 1. Check volume spikes (independent)
            if self.detector.check_volume_spike(stock.symbol, stock.volume, stock.change_percent):
                if self.detector.can_send_alert(stock.symbol, "VOLUME_SPIKE"):
                    self.send_volume_alert(stock)
            
            # 2. Check for 5%+ movers
            if stock.change_percent >= MIN_PERCENT_MOVE:
                self.process_5percent_mover(stock)
    
    def process_5percent_mover(self, stock: StockData):
        """Process stocks that moved 5%+"""
        # Check for bid match
        if self.detector.check_bid_match(stock):
            if self.detector.can_send_alert(stock.symbol, "BID_MATCH"):
                self.send_bid_match_alert(stock)
                self.detector.watchlist.add(stock.symbol)
                return  # Stop if bid found
        
        # If no bid match, check insider trades
        insider_trades = get_insider_trades(stock.symbol)
        for trade in insider_trades:
            shares = int(trade.get('shares', 0))
            if shares >= MIN_INSIDER_SHARES:
                if self.detector.can_send_alert(stock.symbol, "UNUSUAL_ACTIVITY"):
                    self.send_unusual_activity_alert(stock, trade)
                    break
    
    def scan_unusual_options(self):
        """Scan unusual options - runs every 2 minutes"""
        if not self.market_open:
            return
        
        logger.info("🎯 Scanning unusual options...")
        options_data = get_unusual_options()
        
        for option in options_data[:10]:  # Top 10
            base_symbol = option.get('baseSymbol', '')
            if base_symbol and self.detector.can_send_alert(base_symbol, "UNUSUAL_OPTIONS"):
                self.send_unusual_options_alert(option)
    
    def check_watchlist_sales(self):
        """Check watchlist stocks for large sales"""
        if not self.market_open or not self.detector.watchlist:
            return
        
        logger.info(f"👀 Checking {len(self.detector.watchlist)} watchlist stocks...")
        
        for symbol in list(self.detector.watchlist):
            insider_trades = get_insider_trades(symbol)
            for trade in insider_trades:
                if trade.get('transactionType', '').upper() == 'SELL':
                    shares = int(trade.get('shares', 0))
                    if shares >= MIN_INSIDER_SHARES:
                        if self.detector.can_send_alert(symbol, "LARGE_SALE"):
                            self.send_large_sale_alert(symbol, trade)
    
    def send_top10_report(self):
        """Send top 10 gainers report - runs every 5 minutes"""
        if not self.market_open:
            return
        
        # Prevent duplicate 5-min reports
        now = datetime.now()
        current_minute = now.strftime("%Y%m%d%H%M")
        if current_minute in self.detector.processed_5min:
            return
        
        self.detector.processed_5min.add(current_minute)
        
        logger.info("🏆 Sending top 10 report...")
        gainers = get_top_gainers(10)
        
        if gainers:
            now_est = datetime.now(TIMEZONE).strftime("%I:%M %p EST")
            message = f"<b>🏆 TOP 10 GAINERS ({now_est})</b>\n\n"
            
            for i, stock in enumerate(gainers[:10], 1):
                change_emoji = "📈" if stock.change_percent >= 0 else "📉"
                message += f"{i}. <b>{stock.symbol}</b>: ${stock.price:.2f} {change_emoji} ({stock.change_percent:+.1f}%)\n"
            
            send_telegram_message(message, "TOP10")
            logger.info("✅ Top 10 report sent")
    
    # ========== ALERT MESSAGES ==========
    def send_bid_match_alert(self, stock: StockData):
        if stock.bid == BID_MATCH_PRICE_1:
            alert_type = "EXACT MATCH"
        else:
            alert_type = "HIGH VALUE"
        
        message = (
            f"<b>⚡ BID MATCH ALERT: {stock.symbol}</b>\n"
            f"Price: ${stock.price:.2f} ({stock.change_percent:+.1f}%)\n"
            f"Bid: {stock.bid_size} shares @ ${stock.bid:,.2f}\n"
            f"Total: ${stock.bid * stock.bid_size:,.2f}\n"
            f"Type: {alert_type}\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        send_telegram_message(message, "BID_MATCH")
    
    def send_volume_alert(self, stock: StockData):
        message = (
            f"<b>📊 VOLUME SPIKE: {stock.symbol}</b>\n"
            f"Price: ${stock.price:.2f} ({stock.change_percent:+.1f}%)\n"
            f"Volume: {stock.volume:,} shares\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        send_telegram_message(message, "VOLUME_SPIKE")
    
    def send_unusual_activity_alert(self, stock: StockData, insider_trade: Dict):
        message = (
            f"<b>🚨 UNUSUAL ACTIVITY: {stock.symbol}</b>\n"
            f"Price: ${stock.price:.2f} ({stock.change_percent:+.1f}%)\n"
            f"Insider: {insider_trade.get('insider', 'Unknown')}\n"
            f"Transaction: {insider_trade.get('transactionType', 'BUY')} {insider_trade.get('shares', 0):,} shares\n"
            f"Note: Stock up {stock.change_percent:.1f}% but no bid match\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        send_telegram_message(message, "UNUSUAL_ACTIVITY")
    
    def send_unusual_options_alert(self, option: Dict):
        message = (
            f"<b>🎯 UNUSUAL OPTIONS: {option.get('baseSymbol', '')}</b>\n"
            f"Contract: {option.get('symbolType', '')} ${option.get('strikePrice', '')}\n"
            f"Expiry: {option.get('expirationDate', '')}\n"
            f"Volume: {option.get('volume', '0')} contracts\n"
            f"Open Interest: {option.get('openInterest', '0')}\n"
            f"Ratio: {option.get('volumeOpenInterestRatio', '0')}\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        send_telegram_message(message, "UNUSUAL_OPTIONS")
    
    def send_large_sale_alert(self, symbol: str, trade: Dict):
        message = (
            f"<b>📉 LARGE SALE: {symbol}</b>\n"
            f"Sold: {trade.get('shares', 0):,} shares @ ${trade.get('price', 0):.2f}\n"
            f"Total: ${int(trade.get('shares', 0)) * float(trade.get('price', 0)):,.2f}\n"
            f"Note: This stock had previous alerts\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        send_telegram_message(message, "LARGE_SALE")
    
    # ========== SCHEDULER ==========
    def setup_schedule(self):
        """Setup all scheduled tasks"""
        logger.info("🕐 Setting up scheduler...")
        
        # Clear existing jobs
        schedule.clear()
        
        # Main scanner every 10 seconds
        schedule.every(10).seconds.do(self.scan_top_gainers)
        
        # Unusual options every 2 minutes
        schedule.every(120).seconds.do(self.scan_unusual_options)
        
        # Top 10 report every 5 minutes
        schedule.every(300).seconds.do(self.send_top10_report)
        
        # Watchlist sales check every 30 seconds
        schedule.every(30).seconds.do(self.check_watchlist_sales)
        
        # Market hours check every minute
        schedule.every(60).seconds.do(self.check_market_status)
        
        logger.info("✅ Scheduler setup complete")
    
    def check_market_status(self):
        """Check if market is open"""
        was_open = self.market_open
        self.market_open = self.check_market_hours()
        
        if was_open and not self.market_open:
            logger.info("🏁 Market closed. Stopping scans.")
            self.is_running = False
            self.startup_sent = False  # Reset for next day
            send_telegram_message("Market closed. Bot going to sleep until 6 AM EST tomorrow.", "DEBUG")
        elif not was_open and self.market_open:
            logger.info("🚀 Market opened. Starting scans.")
            self.is_running = True
            self.startup_sequence()
        elif self.market_open and not self.startup_sent:
            self.startup_sequence()
    
    def run(self):
        """Main bot loop"""
        logger.info("=" * 60)
        logger.info("🚀 STOCK SCANNER BOT STARTING")
        logger.info("=" * 60)
        
        # Log environment
        logger.info(f"MBOUM_API_KEY: {'✅ SET' if MBOUM_API_KEY else '❌ MISSING'}")
        logger.info(f"TELEGRAM_BOT_TOKEN: {'✅ SET' if TELEGRAM_BOT_TOKEN else '❌ MISSING'}")
        logger.info(f"TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID or '❌ MISSING'}")
        
        # Send startup notification
        send_telegram_message(
            f"🤖 Bot starting...\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M %p EST')}\n"
            f"Status: {'Market OPEN' if self.market_open else 'Market CLOSED'}",
            "DEBUG"
        )
        
        # Initial market check
        self.check_market_status()
        
        # Setup schedule
        self.setup_schedule()
        
        # Main loop
        logger.info("🔄 Entering main loop...")
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
                send_telegram_message("Bot manually stopped", "DEBUG")
                break
            except Exception as e:
                logger.error(f"❌ Unexpected error: {str(e)}")
                send_telegram_message(f"Bot error: {str(e)[:100]}", "DEBUG")
                time.sleep(10)

# ========== ENTRY POINT ==========
if __name__ == "__main__":
    # Check environment variables
    required_vars = ['MBOUM_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"❌ Missing environment variables: {missing_vars}")
        print("ERROR: Missing environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        sys.exit(1)
    
    # Start bot
    try:
        bot = StockScannerBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {str(e)}")
        sys.exit(1)
