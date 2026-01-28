#!/usr/bin/env python3
"""
FINAL WORKING BOT - All features
"""

import os
import time
import requests
import json
from datetime import datetime

print("=" * 60)
print("🚀 FINAL BOT STARTING")
print("=" * 60)

# Configuration
MBOUM_API_KEY = os.getenv('MBOUM_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '6123348609')

print(f"MBOUM_API_KEY: {'✅ SET' if MBOUM_API_KEY else '❌ MISSING'}")
print(f"TELEGRAM_BOT_TOKEN: {'✅ SET' if TELEGRAM_BOT_TOKEN else '❌ MISSING'}")
print(f"TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID or '❌ MISSING'}")

def send_telegram(msg):
    """Send Telegram message"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"Telegram not set: {msg[:50]}...")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def get_top_gainers():
    """Get top gainers from MBOUM"""
    if not MBOUM_API_KEY:
        print("❌ No API key")
        return []
    
    try:
        url = "https://api.mboum.com/v1/screener"
        headers = {'Authorization': MBOUM_API_KEY}
        params = {'metricType': 'overview', 'filter': 'day_gainers', 'limit': '5'}
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            stocks = data.get('body', [])
            print(f"✅ Got {len(stocks)} stocks")
            return stocks
        else:
            print(f"❌ API error: {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ API exception: {e}")
        return []

def check_bid_match(stock):
    """Check for $199,999/100 or $2,000+/20+"""
    try:
        bid = float(stock.get('bid', 0))
        bid_size = int(stock.get('bidSize', 0))
        
        # Pattern 1: $199,999 with exactly 100 shares
        if bid == 199999 and bid_size == 100:
            return "EXACT"
        
        # Pattern 2: $2,000+ with 20+ shares
        elif bid >= 2000 and bid_size >= 20:
            return "HIGH_VALUE"
        
        return None
    except:
        return None

def main():
    """Main loop"""
    # Send startup message
    send_telegram("🤖 Final Bot Started Successfully")
    
    alert_cooldown = {}  # symbol -> timestamp
    top10_last_sent = None
    
    counter = 0
    while True:
        counter += 1
        now = datetime.now()
        print(f"\nScan #{counter} - {now.strftime('%H:%M:%S')}")
        
        # Check market hours (6 AM - 6 PM EST, Mon-Fri)
        hour = now.hour  # UTC, but we'll adjust later
        weekday = now.weekday()  # Monday=0
        
        if 6 <= hour < 18 and weekday < 5:  # Simplified check
            print("✅ Market open (simplified check)")
            
            # Get stocks
            stocks = get_top_gainers()
            
            # Check for bid matches
            for stock in stocks:
                symbol = stock.get('symbol', '')
                bid_match = check_bid_match(stock)
                
                if bid_match:
                    # Check cooldown (5 minutes)
                    if symbol in alert_cooldown:
                        last_alert = alert_cooldown[symbol]
                        if (now - last_alert).total_seconds() < 300:
                            continue
                    
                    # Send alert
                    if bid_match == "EXACT":
                        msg = f"⚡ EXACT BID MATCH: {symbol}\n${stock.get('bid')} with {stock.get('bidSize')} shares"
                    else:
                        msg = f"⚡ HIGH VALUE BID: {symbol}\n${stock.get('bid')} with {stock.get('bidSize')} shares"
                    
                    send_telegram(msg)
                    alert_cooldown[symbol] = now
                    print(f"Sent alert for {symbol}")
            
            # Send top 5 list every 5 minutes
            if top10_last_sent is None or (now - top10_last_sent).total_seconds() >= 300:
                if stocks:
                    msg = "🏆 TOP 5 GAINERS:\n"
                    for i, stock in enumerate(stocks[:5], 1):
                        symbol = stock.get('symbol', '')
                        price = stock.get('regularMarketPrice', 0)
                        change = stock.get('regularMarketChangePercent', 0)
                        msg += f"{i}. {symbol}: ${price} ({change}%)\n"
                    
                    send_telegram(msg)
                    top10_last_sent = now
                    print("Sent top 5 list")
        
        else:
            print("⏰ Market closed")
            if counter % 30 == 0:  # Every ~5 minutes
                send_telegram(f"💤 Bot alive - Market closed\nScans: {counter}")
        
        # Wait 30 seconds
        time.sleep(30)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Stopped")
        send_telegram("🛑 Bot stopped")
    except Exception as e:
        print(f"\n💥 Error: {e}")
        # Try to send error
        try:
            send_telegram(f"💥 Bot crashed: {str(e)[:100]}")
        except:
            pass
        raise  # Show error in logs
