import logging
import re
from typing import Optional

import httpx
from aliexpress_api import AliexpressApi, models
from aliexpress_api.models.request_parameters import SortBy

logger = logging.getLogger(__name__)

PRODUCT_URL_REGEX = re.compile(r"/(\d+)\.html")
SHORT_LINK_REGEX = re.compile(
    r"https?://(?:[a-z]+\.)?(?:aliexpress\.com|a\.aliexpress\.com|s\.click\.aliexpress\.com)"
    r"(?!/\d+\.html)",
    re.IGNORECASE,
)


async def extract_product_id(text: str) -> Optional[str]:
    match = PRODUCT_URL_REGEX.search(text)
    if match:
        return match.group(1)

    if SHORT_LINK_REGEX.search(text):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(text)
                final_url = str(resp.url)
                match = PRODUCT_URL_REGEX.search(final_url)
                if match:
                    return match.group(1)
        except Exception:
            logger.exception("Failed to resolve short link: %s", text)

    return None


def search_products(
    api_key: str,
    api_secret: str,
    query: str | None = None,
    tracking_id: str | None = None,
    category_ids: str | None = None,
    page_size: int = 20,
) -> list[models.Product]:
    api = AliexpressApi(
        key=api_key,
        secret=api_secret,
        language="AR",
        currency="SAR",
        tracking_id=tracking_id,
    )

    response = api.get_products(
        keywords=query or None,
        category_ids=category_ids or None,
        ship_to_country="SA",
        sort=SortBy.SALE_PRICE_ASC,
        page_size=page_size,
    )

    if not response or not response.products:
        return []

    return list(response.products)


def get_product_detail(
    api_key: str,
    api_secret: str,
    product_id: str,
    tracking_id: str | None = None,
) -> Optional[models.Product]:
    api = AliexpressApi(
        key=api_key,
        secret=api_secret,
        language="AR",
        currency="SAR",
        tracking_id=tracking_id,
    )

    products = api.get_products_details(product_ids=product_id)
    if products:
        return products[0]
    return None
