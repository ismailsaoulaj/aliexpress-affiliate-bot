import logging
from dataclasses import dataclass

from aliexpress_api import AliexpressApi, models
from aliexpress_api.models.request_parameters import SortBy

logger = logging.getLogger(__name__)


@dataclass
class Deal:
    product_id: str
    title: str
    image_url: str
    old_price: float
    new_price: float
    discount_percentage: int
    rating: float
    orders_count: int
    affiliate_url: str
    shop_name: str = ""


def _parse_discount(discount_str: str | None) -> int:
    if not discount_str:
        return 0
    cleaned = discount_str.replace("%", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def _safe_float(val: str | None) -> float:
    if not val:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val: int | str | None) -> int:
    if val is None:
        return 0
    return int(val)


def _product_to_deal(product: models.Product) -> Deal:
    old_price = _safe_float(getattr(product, "target_original_price", None))
    new_price = _safe_float(getattr(product, "target_sale_price", None))
    if new_price == 0:
        old_price = _safe_float(getattr(product, "original_price", None))
        new_price = _safe_float(getattr(product, "sale_price", None))
    discount = _parse_discount(getattr(product, "discount", None))
    rating = _safe_float(getattr(product, "evaluate_rate", None))
    orders = _safe_int(getattr(product, "lastest_volume", None))
    affiliate_url = getattr(product, "promotion_link", None) or getattr(product, "product_detail_url", "")

    return Deal(
        product_id=str(getattr(product, "product_id", "")),
        title=getattr(product, "product_title", ""),
        image_url=getattr(product, "product_main_image_url", ""),
        old_price=old_price,
        new_price=new_price,
        discount_percentage=discount,
        rating=rating,
        orders_count=orders,
        affiliate_url=affiliate_url,
        shop_name=getattr(product, "shop_name", ""),
    )


def _filter_deals(products: list[models.Product], min_discount: int) -> list[Deal]:
    deals: list[Deal] = []
    for p in products:
        deal = _product_to_deal(p)
        if deal.discount_percentage >= min_discount and deal.new_price > 0:
            deals.append(deal)
    return deals


def fetch_aliexpress_deals(
    api_key: str,
    api_secret: str,
    tracking_id: str | None = None,
    language: str = "EN",
    currency: str = "USD",
    keywords: str | None = None,
    category_ids: str | None = None,
    min_sale_price: str | int | None = None,
    max_sale_price: str | int | None = None,
    ship_to_country: str | None = None,
    min_discount: int = 40,
    page_no: int = 1,
    page_size: int = 50,
) -> list[Deal]:
    if min_sale_price is not None and min_sale_price != "":
        min_sale_price = int(min_sale_price)
    else:
        min_sale_price = None
    if max_sale_price is not None and max_sale_price != "":
        max_sale_price = int(max_sale_price)
    else:
        max_sale_price = None
    api = AliexpressApi(
        key=api_key,
        secret=api_secret,
        language=language,
        currency=currency,
        tracking_id=tracking_id,
    )

    try:
        response = api.get_products(
            keywords=keywords or None,
            category_ids=category_ids or None,
            min_sale_price=min_sale_price or None,
            max_sale_price=max_sale_price or None,
            ship_to_country=ship_to_country or None,
            page_no=page_no,
            page_size=page_size,
            sort=SortBy.LAST_VOLUME_DESC,
        )
    except Exception:
        logger.exception("AliExpress API request failed")
        raise

    if not response.products:
        logger.info("No products returned from AliExpress API")
        return []

    deals = _filter_deals(response.products, min_discount)
    logger.info(
        "AliExpress API: %d/%d deals passed >= %d%% discount filter",
        len(deals), len(response.products), min_discount,
    )
    return deals
