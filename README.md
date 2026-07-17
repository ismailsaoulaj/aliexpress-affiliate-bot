# AliExpress Affiliate Bot — Home Gadgets Niche

A Telegram bot that fetches AliExpress deals from the official AliExpress Affiliate API and posts them to a Telegram channel on a scheduled interval.

Built with `python-telegram-bot` v22 (async), `APScheduler` v3, `python-aliexpress-api`, and `redis`.

## Features

- Fetches products from the official AliExpress Affiliate API (`aliexpress_affiliate_product_query`)
- Filters for deals with ≥ 40% discount (configurable)
- Posts formatted messages with photo, title, pricing, rating, and affiliate link
- Runs on a configurable schedule (every 6 hours by default)
- Deduplicates using Upstash Redis — survives container restarts
- Runs once immediately on startup, then on schedule
- Sends admin alerts on fetch failures

## Requirements

- Python 3.11+
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- A Telegram channel (public or private) where the bot is admin
- AliExpress Affiliate API credentials (from [AliExpress Open Platform](https://openservice.aliexpress.com))
- An Upstash Redis instance (or any Redis-compatible service)

## Local Setup

```bash
# Clone the repo
git clone <repo-url> && cd aliexpress-bot

# Create virtual environment
python -m venv venv && source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

Edit `.env` and fill in your values:

| Variable                     | Description                                          | Default                    |
| ---------------------------- | ---------------------------------------------------- | -------------------------- |
| `BOT_TOKEN`                  | Telegram Bot API token (from @BotFather)              | —                          |
| `CHANNEL_ID`                 | Channel ID (`@username` or numeric ID)                | —                          |
| `ADMIN_CHAT_ID`              | Chat ID for admin error alerts (optional)             | —                          |
| `ALIEXPRESS_API_KEY`         | AliExpress Affiliate API key                          | —                          |
| `ALIEXPRESS_API_SECRET`      | AliExpress Affiliate API secret                       | —                          |
| `ALIEXPRESS_TRACKING_ID`     | Tracking ID for affiliate links (optional)            | —                          |
| `ALIEXPRESS_LANGUAGE`        | API response language                                 | `EN`                       |
| `ALIEXPRESS_CURRENCY`        | API response currency                                 | `USD`                      |
| `ALIEXPRESS_KEYWORDS`        | Keywords to filter products (optional)                | —                          |
| `ALIEXPRESS_CATEGORY_IDS`    | Category IDs to filter by (optional)                  | —                          |
| `ALIEXPRESS_MIN_SALE_PRICE`  | Minimum sale price filter (optional)                  | —                          |
| `ALIEXPRESS_MAX_SALE_PRICE`  | Maximum sale price filter (optional)                  | —                          |
| `ALIEXPRESS_SHIP_TO_COUNTRY` | Ship-to country filter (optional)                     | —                          |
| `REDIS_URL`                  | Redis connection string (e.g. from Upstash)           | —                          |
| `FETCH_INTERVAL_HOURS`       | How often to check for new deals                      | `6`                        |
| `MIN_DISCOUNT`               | Minimum discount percentage to include                | `40`                       |

```bash
# Run the bot
python bot.py
```

## Railway Deployment

### Manual steps

1. Push this repo to GitHub.
2. Go to [Railway Dashboard](https://railway.app/dashboard) → **New Project** → **Deploy from GitHub repo**.
3. Railway auto-detects Python; `requirements.txt` and `runtime.txt` are picked up automatically.
4. Add the following environment variables in Railway:
   - `BOT_TOKEN`
   - `CHANNEL_ID`
   - `ALIEXPRESS_API_KEY`
   - `ALIEXPRESS_API_SECRET`
   - `REDIS_URL`
5. (Optional) Override `FETCH_INTERVAL_HOURS` or `MIN_DISCOUNT` if desired.
6. Deploy — the bot starts immediately.

> **Note:** Deduplication uses Upstash Redis (external), so history persists across restarts.

## Project Structure

```
aliexpress-bot/
├── bot.py            # Entry point, scheduler, message sending
├── config.py         # Env variable loading
├── deals_api.py      # AliExpress Affiliate API fetcher + Deal dataclass
├── posted_store.py   # Redis-backed deduplication store
├── requirements.txt  # Python dependencies
├── runtime.txt       # Python version for Railway
└── README.md
```
