# AGENTS.md — AliExpress Affiliate Bot

## Run

```bash
source venv/bin/activate
python bot.py
```

No test, lint, typecheck, or formatter config. Works out of the box — no `pyproject.toml` needed.

## Project structure

Single-module Python project (3.11). No packages, no test files.

| File | Role |
|---|---|
| `bot.py` | Entrypoint: scheduler, message formatting, send loop |
| `config.py` | Loads env vars via `python-dotenv` |
| `deals_api.py` | Fetches AliExpress Affiliate API via `python-aliexpress-api`, discount filter |
| `posted_store.py` | Redis-backed (Upstash) dedup store via `redis.asyncio` |

## Environment

`.env` is required at project root — `.env.example` documents all vars.

**Mandatory**: `BOT_TOKEN`, `CHANNEL_ID`, `ALIEXPRESS_API_KEY`, `ALIEXPRESS_API_SECRET`, `REDIS_URL`.

**Affiliate API**: Get credentials at https://openservice.aliexpress.com — the app must have `aliexpress_affiliate_product_query` permission.

**Optional**: `ADMIN_CHAT_ID`, `FETCH_INTERVAL_HOURS`, `MIN_DISCOUNT`, `ALIEXPRESS_TRACKING_ID`, `ALIEXPRESS_LANGUAGE`, `ALIEXPRESS_CURRENCY`, `ALIEXPRESS_KEYWORDS`, `ALIEXPRESS_CATEGORY_IDS`, `ALIEXPRESS_MIN_SALE_PRICE`, `ALIEXPRESS_MAX_SALE_PRICE`, `ALIEXPRESS_SHIP_TO_COUNTRY`.

## Behavior quirks

- If `ADMIN_CHAT_ID` is set, the bot sends an alert to that chat when AliExpress API fetch fails
- Runs once immediately on startup, then every `FETCH_INTERVAL_HOURS` (default 6)
- Queries `aliexpress_affiliate_product_query` via `python-aliexpress-api` SDK
- Uses `target_sale_price` and `target_original_price` for USD pricing; falls back to raw `sale_price`
- Filters deals with discount < `MIN_DISCOUNT` (default 40%)
- Sends `send_photo` with HTML caption; 1.5s `asyncio.sleep` between sends to avoid Telegram rate limits
- Dedup uses Upstash Redis (`REDIS_URL`) — survives container restarts
- Uses `APScheduler` AsyncIOScheduler with an idle `while True: await asyncio.sleep(3600)` loop
