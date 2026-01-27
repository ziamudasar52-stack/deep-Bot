#!/usr/bin/env python3
"""
ULTIMATE STOCK SCANNER BOT - DEEP BOT VERSION
Version: 3.0
Author: DEEP BOT Stock Alert System
Description: Real-time stock scanner using MBOUM API with Telegram alerts
"""

import os
import time
import requests
import schedule
import json
from datetime import datetime, timedelta
import pytz
from typing import Dict, List, Optional, Set, Tuple
import logging
from dataclasses import dataclass
from telegram import Bot
from telegram.error import TelegramError
import sys
import threading

# ========== CONFIGURATION ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Environment Variables
MBOUM_API_KEY = os.getenv('MBOUM_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Validate environment variables
if not MBOUM_API_KEY:
    logger.error("❌ MBOUM_API_KEY not found in environment variables")
    sys.exit(1)
if not TELEGRAM_BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN not found in environment variables")
    sys.exit(1)
if not TELEGRAM_CHAT_ID:
    logger.error("❌ TELEGRAM_CHAT_ID not found in environment variables")
    sys.exit(1)

# API Configuration
BASE_URL = "https://api.mboum.com"
HEADERS = {'Authorization': MBOUM_API_KEY}  # Key already includes "Bearer"

# Bot Configuration
TIMEZONE = pytz.timezone('America/New_York')
SCAN_INTERVAL = 10  # seconds for main scanner
UNUSUAL_OPTIONS_INTERVAL = 120  # seconds (2 minutes)
TOP10_INTERVAL = 300  # seconds (5 minutes)
MARKET_CHECK_INTERVAL = 60  # seconds

# Alert Thresholds
BID_MATCH_PRICE_1 = 199999
BID_MATCH_SHARES_1 = 100
BID_MATCH_PRICE_2 = 2000
BID_MATCH_SHARES_2 = 20
MIN_PERCENT_MOVE = 5
MIN_INSIDER_SHARES = 10000
VOLUME_MULTIPLIERS = {
    (1, 10): 10,
    (10, 50): 20,
    (50, 100): 30,
    (100, 200): 50,
    (200, float('inf')): 100
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

@dataclass
class OptionData:
    symbol: str
    base_symbol: str
    option_type: str
    strike: float
    expiration: str
    volume: int
    open_interest: int
    last_price: float
    volatility: float
    trade_time: str

# ========== API FUNCTIONS ==========
def make_api_call(endpoint: str, params: Dict = None) -> Optional[Dict]:
    """Make API call to MBOUM"""
    if not MBOUM_API_KEY:
        return None
    
    url = f"{BASE_URL}{endpoint}"
    
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"API Connection Error: {str(e)}")
        return None

def get_top_gainers(limit: int = 50) -> List[StockData]:
    """Get top gainers from screener"""
    logger.info(f"🔍 Getting top {limit} gainers...")
    
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
    
    try:
        for item in data['body'][:limit]:
            try:
                symbol = item.get('symbol', '')
                if not symbol:
                    continue
                
                # Extract price and change
                price = float(item.get('regularMarketPrice', 0))
                change_percent = float(item.get('regularMarketChangePercent', 0))
                volume = int(item.get('regularMarketVolume', 0))
                
                # Extract bid/ask data
                bid = float(item.get('bid', 0))
                bid_size = int(item.get('bidSize', 0))
                ask = float(item.get('ask', 0))
                ask_size = int(item.get('askSize', 0))
                prev_close = float(item.get('regularMarketPreviousClose', 0))
                
                stock = StockData(
                    symbol=str(symbol),
                    price=price,
                    change_percent=change_percent,
                    volume=volume,
                    bid=bid,
                    bid_size=bid_size,
                    ask=ask,
                    ask_size=ask_size,
                    previous_close=prev_close
                )
                stocks.append(stock)
                
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing stock {item.get('symbol', 'unknown')}: {e}")
                continue
        
        logger.info(f"✅ Found {len(stocks)} gainers")
        return sorted(stocks, key=lambda x: x.change_percent, reverse=True)
        
    except Exception as e:
        logger.error(f"❌ Error processing screener data: {str(e)}")
        return []

def get_unusual_options() -> List[OptionData]:
    """Get unusual options activity"""
    logger.info("🎯 Getting unusual options...")
    
    data = make_api_call("/v1/markets/options/unusual-options-activity", {
        'type': 'STOCKS',
        'page': '1'
    })
    
    if not data or 'body' not in data:
        logger.info("ℹ️ No unusual options data")
        return []
    
    options = []
    
    try:
        for item in data['body']:
            try:
                option = OptionData(
                    symbol=item.get('symbol', ''),
                    base_symbol=item.get('baseSymbol', ''),
                    option_type=item.get('symbolType', ''),
                    strike=float(item.get('strikePrice', 0)),
                    expiration=item.get('expirationDate', ''),
                    volume=int(item.get('volume', '0').replace(',', '')),
                    open_interest=int(item.get('openInterest', '0')),
                    last_price=float(item.get('lastPrice', 0)),
                    volatility=float(item.get('volatility', '0%').replace('%', '')),
                    trade_time=item.get('tradeTime', '')
                )
                options.append(option)
                
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing option {item.get('symbol', 'unknown')}: {e}")
                continue
        
        logger.info(f"✅ Found {len(options)} unusual options")
        return options
        
    except Exception as e:
        logger.error(f"❌ Error processing options: {str(e)}")
        return []

def get_insider_trades(symbol: str = None) -> List[Dict]:
    """Get insider trades"""
    params = {'minValue': '10000', 'page': '1', 'limit': '20'}
    if symbol:
        params['ticker'] = symbol
    
    data = make_api_call("/v1/insider-trades", params)
    return data if data else []

def get_market_info() -> Optional[Dict]:
    """Get market status"""
    return make_api_call("/v2/market-info")

# ========== ALERT DETECTION CLASS ==========
class AlertDetector:
    def __init__(self):
        self.alert_history: Dict[str, datetime] = {}
        self.watchlist: Set[str] = set()
        self.volume_history: Dict[str, Dict] = {}
    
    def check_bid_match(self, stock: StockData) -> Tuple[bool, str]:
        """Check for bid match patterns"""
        # Pattern 1: Exact $199,999 with 100 shares
        if stock.bid == BID_MATCH_PRICE_1 and stock.bid_size == BID_MATCH_SHARES_1:
            return True, "EXACT"
        
        # Pattern 2: $2,000+ with 20+ shares
        elif stock.bid >= BID_MATCH_PRICE_2 and stock.bid_size >= BID_MATCH_SHARES_2:
            return True, "HIGH_VALUE"
        
        return False, ""
    
    def check_volume_spike(self, symbol: str, current_volume: int, percent_change: float) -> bool:
        """Check for volume spike"""
        if symbol not in self.volume_history:
            self.volume_history[symbol] = {'samples': [], 'avg': current_volume}
        
        # Add current volume to history
        self.volume_history[symbol]['samples'].append(current_volume)
        if len(self.volume_history[symbol]['samples']) > 30:
            self.volume_history[symbol]['samples'].pop(0)
        
        # Calculate average
        if len(self.volume_history[symbol]['samples']) > 5:
            avg = sum(self.volume_history[symbol]['samples']) / len(self.volume_history[symbol]['samples'])
            self.volume_history[symbol]['avg'] = avg
            
            # Get multiplier based on % move
            multiplier = 10  # default
            for (min_p, max_p), mult in VOLUME_MULTIPLIERS.items():
                if min_p <= abs(percent_change) < max_p:
                    multiplier = mult
                    break
            
            # Check spike
            if avg > 0 and current_volume > (avg * multiplier):
                return True
        
        return False
    
    def can_send_alert(self, symbol: str, alert_type: str) -> bool:
        """Prevent duplicate alerts"""
        key = f"{symbol}_{alert_type}"
        now = datetime.now()
        
        if key in self.alert_history:
            last_alert = self.alert_history[key]
            if (now - last_alert).total_seconds() < 300:  # 5 minutes cooldown
                return False
        
        self.alert_history[key] = now
        return True
    
    def add_to_watchlist(self, symbol: str):
        """Add stock to watchlist for sales monitoring"""
        self.watchlist.add(symbol)

# ========== TELEGRAM BOT CLASS ==========
class TelegramBot:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.chat_id = TELEGRAM_CHAT_ID
    
    def send_message(self, message: str, alert_type: str = "INFO"):
        """Send message to Telegram with DEEP BOT tag"""
        try:
            # Add emoji and DEEP BOT tag
            emojis = {
                "STARTUP": "☀️",
                "BID_MATCH": "⚡",
                "VOLUME_SPIKE": "📊",
                "UNUSUAL_ACTIVITY": "🚨",
                "UNUSUAL_OPTIONS": "🎯",
                "HALT_ALERT": "⏸️",
                "LARGE_SALE": "📉",
                "TOP10": "🏆",
                "ERROR": "❌",
                "DEBUG": "🔧"
            }
            
            emoji = emojis.get(alert_type, "ℹ️")
            formatted_msg = f"{emoji} {message}\n\n🔹 DEEP BOT"
            
            self.bot.send_message(chat_id=self.chat_id, text=formatted_msg)
            logger.info(f"📤 Telegram sent: {alert_type}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Telegram send error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"❌ Telegram exception: {str(e)}")
            return False

# ========== MAIN BOT CLASS ==========
class StockScannerBot:
    def __init__(self):
        self.detector = AlertDetector()
        self.telegram = TelegramBot()
        self.is_running = False
        self.market_open = False
        self.startup_sent = False
        
    def check_market_hours(self) -> bool:
        """Check if within market hours"""
        now_est = datetime.now(TIMEZONE)
        
        # Check weekend
        if now_est.weekday() >= 5:
            return False
        
        # Check time (6 AM - 6 PM EST)
        current_hour = now_est.hour
        if 6 <= current_hour < 18:
            return True
        
        return False
    
    def startup(self):
        """Send startup message"""
        if not self.startup_sent and self.market_open:
            self.telegram.send_message(
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
            # Check volume spikes
            if self.detector.check_volume_spike(stock.symbol, stock.volume, stock.change_percent):
                if self.detector.can_send_alert(stock.symbol, "VOLUME_SPIKE"):
                    self.send_volume_alert(stock)
            
            # Check 5%+ movers
            if stock.change_percent >= MIN_PERCENT_MOVE:
                self.process_5percent_mover(stock)
    
    def process_5percent_mover(self, stock: StockData):
        """Process stocks that moved 5%+"""
        # Check for bid match
        bid_found, bid_type = self.detector.check_bid_match(stock)
        
        if bid_found:
            if self.detector.can_send_alert(stock.symbol, "BID_MATCH"):
                self.send_bid_match_alert(stock, bid_type)
                self.check_halt_status(stock.symbol)
                self.detector.add_to_watchlist(stock.symbol)
                return
        
        # If no bid match, check insider trades
        if not bid_found:
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
        options = get_unusual_options()
        
        for option in options[:15]:  # Process top 15
            # Check for unusual activity
            if option.open_interest > 0:
                ratio = option.volume / option.open_interest
                
                if ratio >= 5 or option.volume >= 5000:
                    if self.detector.can_send_alert(option.base_symbol, "UNUSUAL_OPTIONS"):
                        self.send_unusual_options_alert(option)
    
    def check_halt_status(self, symbol: str):
        """Check if stock is halted"""
        market_info = get_market_info()
        if market_info and market_info.get('halted', False):
            if self.detector.can_send_alert(symbol, "HALT_ALERT"):
                self.send_halt_alert(symbol)
    
    def monitor_watchlist(self):
        """Monitor watchlist stocks for large sales"""
        if not self.market_open:
            return
        
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
        
        logger.info("🏆 Sending top 10 report...")
        gainers = get_top_gainers(10)
        
        if gainers:
            now_est = datetime.now(TIMEZONE).strftime("%I:%M %p EST")
            message = f"TOP 10 GAINERS ({now_est})\n\n"
            
            for i, stock in enumerate(gainers[:10], 1):
                message += f"{i}. {stock.symbol}: ${stock.price:.2f} (+{stock.change_percent:.1f}%)\n"
            
            self.telegram.send_message(message, "TOP10")
    
    # ========== ALERT MESSAGE FUNCTIONS ==========
    def send_bid_match_alert(self, stock: StockData, bid_type: str):
        """Send bid match alert"""
        if bid_type == "EXACT":
            title = "EXACT BID MATCH ALERT"
            detail = f"100 shares @ ${stock.bid:,.2f}"
        else:
            title = "HIGH VALUE BID MATCH"
            detail = f"{stock.bid_size} shares @ ${stock.bid:,.2f}"
        
        message = (
            f"{title}: {stock.symbol}\n"
            f"Price: ${stock.price:.2f} (+{stock.change_percent:.1f}%)\n"
            f"Bid: {detail}\n"
            f"Total Value: ${stock.bid * stock.bid_size:,.2f}\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        self.telegram.send_message(message, "BID_MATCH")
    
    def send_volume_alert(self, stock: StockData):
        """Send volume spike alert"""
        avg = self.detector.volume_history[stock.symbol]['avg']
        multiplier = stock.volume / avg if avg > 0 else 0
        
        message = (
            f"VOLUME SPIKE: {stock.symbol}\n"
            f"Price: ${stock.price:.2f} (+{stock.change_percent:.1f}%)\n"
            f"Volume: {stock.volume:,} shares ({multiplier:.1f}x average)\n"
            f"Average: {int(avg):,} shares\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        self.telegram.send_message(message, "VOLUME_SPIKE")
    
    def send_unusual_activity_alert(self, stock: StockData, trade: Dict):
        """Send unusual activity alert"""
        message = (
            f"UNUSUAL ACTIVITY: {stock.symbol}\n"
            f"Price: ${stock.price:.2f} (+{stock.change_percent:.1f}%)\n"
            f"Insider: {trade.get('insider', '')}\n"
            f"Transaction: {trade.get('shares', 0):,} shares @ ${trade.get('price', 0):.2f}\n"
            f"Total: ${int(trade.get('shares', 0)) * float(trade.get('price', 0)):,.2f}\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        self.telegram.send_message(message, "UNUSUAL_ACTIVITY")
    
    def send_unusual_options_alert(self, option: OptionData):
        """Send unusual options alert"""
        ratio = option.volume / option.open_interest if option.open_interest > 0 else 0
        
        message = (
            f"UNUSUAL OPTIONS: {option.base_symbol}\n"
            f"Contract: {option.option_type} ${option.strike:.2f}\n"
            f"Expiry: {option.expiration}\n"
            f"Volume: {option.volume:,} contracts\n"
            f"Open Interest: {option.open_interest:,}\n"
            f"Ratio: {ratio:.1f}x\n"
            f"Last: ${option.last_price:.2f}\n"
            f"Volatility: {option.volatility:.1f}%\n"
            f"Time: {option.trade_time} EST"
        )
        self.telegram.send_message(message, "UNUSUAL_OPTIONS")
    
    def send_halt_alert(self, symbol: str):
        """Send halt alert"""
        message = (
            f"HALT ALERT: {symbol}\n"
            f"Stock halted after bid match\n"
            f"Halt Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        self.telegram.send_message(message, "HALT_ALERT")
    
    def send_large_sale_alert(self, symbol: str, trade: Dict):
        """Send large sale alert"""
        message = (
            f"LARGE SALE: {symbol}\n"
            f"Sold: {trade.get('shares', 0):,} shares @ ${trade.get('price', 0):.2f}\n"
            f"Total: ${int(trade.get('shares', 0)) * float(trade.get('price', 0)):,.2f}\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M:%S %p EST')}"
        )
        self.telegram.send_message(message, "LARGE_SALE")
    
    # ========== SCHEDULER ==========
    def setup_schedule(self):
        """Setup all scheduled tasks"""
        logger.info("🕐 Setting up scheduler...")
        
        # Main scanner every 10 seconds
        schedule.every(SCAN_INTERVAL).seconds.do(self.scan_top_gainers)
        
        # Unusual options every 2 minutes
        schedule.every(UNUSUAL_OPTIONS_INTERVAL).seconds.do(self.scan_unusual_options)
        
        # Top 10 report every 5 minutes
        schedule.every(TOP10_INTERVAL).seconds.do(self.send_top10_report)
        
        # Watchlist monitor every 30 seconds
        schedule.every(30).seconds.do(self.monitor_watchlist)
        
        # Market check every minute
        schedule.every(MARKET_CHECK_INTERVAL).seconds.do(self.check_market_status)
        
        logger.info("✅ Scheduler setup complete")
    
    def check_market_status(self):
        """Check if market is open"""
        was_open = self.market_open
        self.market_open = self.check_market_hours()
        
        if was_open and not self.market_open:
            logger.info("🏁 Market closed. Stopping scans.")
            self.is_running = False
            self.startup_sent = False
        elif not was_open and self.market_open:
            logger.info("🚀 Market opened. Starting scans.")
            self.is_running = True
            self.startup()
        elif self.market_open and not self.startup_sent:
            self.startup()
    
    def run(self):
        """Main bot loop"""
        logger.info("=" * 60)
        logger.info("🚀 STARTING DEEP BOT STOCK SCANNER")
        logger.info(f"MBOUM Key: {'✅ SET' if MBOUM_API_KEY else '❌ MISSING'}")
        logger.info(f"Telegram Token: {'✅ SET' if TELEGRAM_BOT_TOKEN else '❌ MISSING'}")
        logger.info(f"Chat ID: {TELEGRAM_CHAT_ID}")
        logger.info("=" * 60)
        
        # Initial market check
        self.check_market_status()
        
        # Setup schedule
        self.setup_schedule()
        
        # Send initial status
        self.telegram.send_message(
            f"DEEP BOT started\n"
            f"Time: {datetime.now(TIMEZONE).strftime('%I:%M %p EST')}\n"
            f"Market: {'OPEN' if self.market_open else 'CLOSED'}",
            "DEBUG"
        )
        
        # Main loop
        logger.info("🔄 Entering main loop...")
        while True:
            try:
                if self.is_running:
                    schedule.run_pending()
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
                self.telegram.send_message("Bot manually stopped", "DEBUG")
                break
            except Exception as e:
                logger.error(f"❌ Unexpected error: {str(e)}")
                self.telegram.send_message(f"Bot error: {str(e)[:100]}", "ERROR")
                time.sleep(10)

# ========== ENTRY POINT ==========
if __name__ == "__main__":
    bot = StockScannerBot()
    bot.run()