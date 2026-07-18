# AGENTS.md — AliExpress Affiliate Bot

## Run

```bash
source venv/bin/activate

# Channel publisher
python bot.py

# Search bot (separate process)
python search_bot/search_bot.py
```

No test, lint, typecheck, or formatter config. Works out of the box — no `pyproject.toml` needed.

## Project structure

Python 3.11 project with two independent bots sharing env vars and API credentials.

| File / Directory | Role |
|---|---|
| `bot.py` | Channel publisher: scheduler, message formatting, send loop |
| `config.py` | Loads env vars via `python-dotenv` |
| `deals_api.py` | Fetches AliExpress Affiliate API via `python-aliexpress-api`, discount filter |
| `posted_store.py` | Redis-backed (Upstash) dedup store via `redis.asyncio` |
| `search_bot/` | Interactive search bot (standalone package) |
| `search_bot/search_bot.py` | Entry point: handlers, alert checker background job |
| `search_bot/search_api.py` | Search + product detail + URL extraction (incl. short link resolution) |
| `search_bot/price_store.py` | Redis-backed price history (per product_id) + alert storage |
| `search_bot/smart_score.py` | Composite ranking formula: price 35%, rating 30%, orders 20%, discount 15% |

## Environment

`.env` is required at project root — `.env.example` documents all vars.

**Mandatory for channel publisher**: `BOT_TOKEN`, `CHANNEL_ID`, `ALIEXPRESS_API_KEY`, `ALIEXPRESS_API_SECRET`, `REDIS_URL`.

**Mandatory for search bot**: `SEARCH_BOT_TOKEN`, `ALIEXPRESS_API_KEY`, `ALIEXPRESS_API_SECRET`, `REDIS_URL`.

**Affiliate API**: Get credentials at https://openservice.aliexpress.com — the app must have `aliexpress_affiliate_product_query` permission.

**Optional**: `ADMIN_CHAT_ID`, `FETCH_INTERVAL_HOURS`, `MIN_DISCOUNT`, `ALIEXPRESS_TRACKING_ID`, `ALIEXPRESS_LANGUAGE`, `ALIEXPRESS_CURRENCY`, `ALIEXPRESS_KEYWORDS`, `ALIEXPRESS_CATEGORY_IDS`, `ALIEXPRESS_MIN_SALE_PRICE`, `ALIEXPRESS_MAX_SALE_PRICE`, `ALIEXPRESS_SHIP_TO_COUNTRY`.

## Behaviour quirks — Channel Publisher

- If `ADMIN_CHAT_ID` is set, the bot sends an alert to that chat when AliExpress API fetch fails
- Runs once immediately on startup, then every `FETCH_INTERVAL_HOURS` (default 6)
- Queries `aliexpress_affiliate_product_query` via `python-aliexpress-api` SDK
- Uses `target_sale_price` and `target_original_price` for USD pricing; falls back to raw `sale_price`
- Filters deals with discount < `MIN_DISCOUNT` (default 40%)
- Sends `send_photo` with HTML caption; 1.5s `asyncio.sleep` between sends to avoid Telegram rate limits
- Dedup uses Upstash Redis (`REDIS_URL`) — survives container restarts
- Uses `APScheduler` AsyncIOScheduler with an idle `while True: await asyncio.sleep(3600)` loop

## Behaviour quirks — Search Bot

- All user-facing text is in Arabic
- `/search <query>` or just type keywords / paste an AliExpress URL
- Short links (`a.aliexpress.com/_…`) are resolved via HTTP redirect to extract the product ID
- Fetches 20 products, re-ranks by smart score, returns top 3
- Price history tracked per product_id (30 entries, 7-day TTL)
- Price alerts checked every 6 hours via APScheduler background job
- Commands auto-registered on startup via `set_my_commands`
