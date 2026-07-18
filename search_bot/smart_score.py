import logging

logger = logging.getLogger(__name__)


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_discount(discount_str: str | None) -> float:
    if not discount_str:
        return 0.0
    cleaned = discount_str.replace("%", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def smart_score(
    price: float,
    rating: float,
    orders: int,
    discount: float,
    max_price_in_batch: float,
    min_price_in_batch: float,
) -> float:
    price_range = max_price_in_batch - min_price_in_batch
    if price_range == 0:
        price_score = 1.0
    else:
        price_score = (max_price_in_batch - price) / price_range

    rating_score = rating / 5.0
    orders_score = min(orders / 10000, 1.0)
    discount_score = discount / 100.0

    return (
        price_score * 0.35
        + rating_score * 0.30
        + orders_score * 0.20
        + discount_score * 0.15
    )
