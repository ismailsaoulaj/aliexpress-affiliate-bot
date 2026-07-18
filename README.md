# AliExpress Affiliate Bot

Two Telegram bots powered by the official AliExpress Affiliate API — one that automatically posts discounted deals to a channel on a schedule, and another that lets users search for products interactively.

Built with `python-telegram-bot` v22 (async), `APScheduler` v3, `python-aliexpress-api`, and `redis`.

## Bots

### 1. Channel Publisher (`bot.py`)

Fetches AliExpress deals from the official Affiliate API and posts them to a Telegram channel on a scheduled interval.

- Fetches products via `aliexpress_affiliate_product_query`
- Filters for deals with ≥ configurable discount (default 40%)
- Posts formatted messages with photo, title, pricing, rating, and affiliate link
- Dynamic currency symbol based on `ALIEXPRESS_CURRENCY`
- Pagination support — cycles through multiple pages
- Deduplication using Upstash Redis
- Health check server for platforms like Railway
- Docker support

### 2. Search Bot (`search_bot/search_bot.py`)

An interactive bot that lets users search for products, get price alerts, and browse categories — runs as a separate process.

- **Product Search** — text keywords, AliExpress URLs (including short links), or category browsing
- **Smart Ranking** — composite score (price 35%, rating 30%, orders 20%, discount 15%), batch-normalized
- **Price Drop Alerts** — set target price per product, background check every 6 hours
- **Price History** — 7-day trend tracking, shows 📉/📈 indicators on result cards
- **Category Browsing** — 6 popular categories via `/start` inline buttons
- **Search History** — last 10 searches, re-runnable via inline buttons
- **All in Arabic** — user-facing text is fully localized

## Requirements

- Python 3.11+
- Telegram Bot Token(s) from [@BotFather](https://t.me/BotFather)
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
| `BOT_TOKEN`                  | Telegram Bot API token (channel publisher)            | —                          |
| `SEARCH_BOT_TOKEN`           | Telegram Bot API token (search bot)                   | —                          |
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

### Run the Channel Publisher

```bash
python bot.py
```

### Run the Search Bot

```bash
python search_bot/search_bot.py
```

Register the search bot commands with [@BotFather](https://t.me/BotFather) (`/setcommands`):

```
start - ابدأ هنا واختر فئة
search - ابحث عن منتج: /search كفر ايفون
myalerts - اعرض تنبيهاتي النشطة
cancelalert - ألغِ تنبيهاً: /cancelalert 3
history - اعرض آخر 10 بحثات
help - اعرض جميع الأوامر
```

> The bot also auto-registers commands on startup via the Telegram API.

## Docker

```bash
docker build -t aliexpress-bot .
docker run -it --rm --env-file .env -p 8080:8080 aliexpress-bot
```

Note: The search bot is not included in the Docker build by default. To add it, modify the `Procfile` or run it separately.

## Railway Deployment

1. Push this repo to GitHub.
2. Go to [Railway Dashboard](https://railway.app/dashboard) → **New Project** → **Deploy from GitHub repo**.
3. Railway auto-detects Python; `requirements.txt`, `runtime.txt`, and `Procfile` are picked up automatically.
4. Add the env variables needed for your chosen bot.
5. Deploy — the bot(s) start immediately.

The `Procfile` defines two processes:
- `worker` — channel publisher bot (`python bot.py`)
- `search` — search bot (`python search_bot/search_bot.py`)

Run the search bot on Railway by setting the `RAILWAY_PROCESS_NAME` env var to `search` or adjust your Railway service command.

## Project Structure

```
aliexpress-affiliate-bot/
├── bot.py                # Channel publisher: scheduler, message formatting, health check
├── config.py             # Env variable loading + currency symbols
├── deals_api.py          # AliExpress Affiliate API fetcher + Deal dataclass
├── posted_store.py       # Redis-backed deduplication store
├── search_bot/           # Interactive search bot (standalone)
│   ├── search_bot.py     # Entry point, handlers, alert checker
│   ├── search_api.py     # Search + product detail + URL extraction
│   ├── price_store.py    # Redis-backed price history + alert store
│   ├── smart_score.py    # Smart ranking formula
│   └── __init__.py
├── Dockerfile            # Container image definition
├── .dockerignore         # Files excluded from Docker build
├── Procfile              # Railway process definitions
├── requirements.txt      # Python dependencies
├── runtime.txt           # Python version for Railway
└── README.md
```
