# AliExpress Affiliate Bot

A Telegram bot that fetches AliExpress deals from the official AliExpress Affiliate API and posts them to a Telegram channel on a scheduled interval.

Built with `python-telegram-bot` v22 (async), `APScheduler` v3, `python-aliexpress-api`, and `redis`.

## Features

- Fetches products from the official AliExpress Affiliate API (`aliexpress_affiliate_product_query`)
- Filters for deals with ≥ configurable discount (default 40%)
- Posts formatted messages with photo, title, pricing, rating, and affiliate link
- Dynamic currency symbol based on `ALIEXPRESS_CURRENCY` (SAR, USD, EUR, etc.)
- Pagination support — cycles through multiple pages to discover fresh products
- Runs on a configurable schedule (every 6 hours by default)
- Deduplication using Upstash Redis — survives container restarts
- Sends admin alerts on fetch failures
- Health check server for platforms like Railway
- Docker support

## Requirements

- Python 3.11+
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- A Telegram channel (public or private) where the bot is admin
- AliExpress Affiliate API credentials (from [AliExpress Open Platform](https://openservice.aliexpress.com))
- An Upstash Redis instance (or any Redis-compatible service)

## Local Setup

```bash
git clone https://github.com/ismailsaoulaj/aliexpress-affiliate-bot.git && cd aliexpress-affiliate-bot

python -m venv venv && source venv/bin/activate

pip install -r requirements.txt

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
| `MAX_PAGES`                  | Number of pages to cycle through                      | `5`                        |
| `PORT`                       | Health check server port                              | `8080`                     |

```bash
python bot.py
```

## Docker

```bash
docker build -t aliexpress-bot .
docker run -it --rm --env-file .env -p 8080:8080 aliexpress-bot
```

## Railway Deployment

1. Push this repo to GitHub.
2. Go to [Railway Dashboard](https://railway.app/dashboard) → **New Project** → **Deploy from GitHub repo**.
3. Railway auto-detects Python; `requirements.txt`, `runtime.txt`, and `Procfile` are picked up automatically.
4. Add the following environment variables in Railway:
   - `BOT_TOKEN`
   - `CHANNEL_ID`
   - `ALIEXPRESS_API_KEY`
   - `ALIEXPRESS_API_SECRET`
   - `REDIS_URL`
   - `ALIEXPRESS_CURRENCY` (set to `SAR` for Saudi Riyal)
5. (Optional) Override `FETCH_INTERVAL_HOURS`, `MIN_DISCOUNT`, or `MAX_PAGES` if desired.
6. Deploy — the bot starts immediately.

> **Note:** Deduplication uses Upstash Redis (external), so history persists across restarts.

## Project Structure

```
aliexpress-affiliate-bot/
├── bot.py            # Entry point, scheduler, message formatting, health check
├── config.py         # Env variable loading + currency symbols
├── deals_api.py      # AliExpress Affiliate API fetcher + Deal dataclass
├── posted_store.py   # Redis-backed deduplication store
├── Dockerfile        # Container image definition
├── .dockerignore     # Files excluded from Docker build
├── Procfile          # Railway worker process
├── requirements.txt  # Python dependencies
├── runtime.txt       # Python version for Railway
└── README.md
```
