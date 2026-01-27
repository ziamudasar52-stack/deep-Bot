# DEEP BOT - Stock Scanner Bot

Real-time stock scanner using MBOUM API with Telegram alerts. This bot scans for unusual activity, bid matches, volume spikes, and sends alerts during market hours.

## Features
- **6 AM - 6 PM EST** operation only
- **Monday-Friday** only (no weekends/holidays)
- **10-second** scanning intervals
- **7 Alert Types:**
  1. ⚡ Bid Match Alerts ($199,999/100 or $2,000+/20+)
  2. 📊 Volume Spike Alerts (smart thresholds)
  3. 🚨 Unusual Activity Alerts (insider trades)
  4. 🎯 Unusual Options Alerts (every 2 minutes)
  5. ⏸️ Halt Alerts (after bid matches)
  6. 📉 Large Sale Alerts (watchlist stocks)
  7. 🏆 Top 10 Gainers List (every 5 minutes)

## Setup

### 1. Railway Deployment
1. Go to [Railway.app](https://railway.app)
2. Click "New Project" → "Deploy from GitHub repo"
3. Connect your GitHub account
4. Select your `stock-scanner-bot` repository
5. Railway will automatically deploy

### 2. Environment Variables
In Railway dashboard, add these variables:
