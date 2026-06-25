from __future__ import annotations

from app.models import OrderItem

# Product families that are never treated as personal-hygiene items.
NON_HYGIENE_CATEGORIES = frozenset(
    {
        "electronics",
        "computer hardware",
        "mobile devices",
        "home",
        "kitchen",
        "furniture",
        "books",
        "toys",
        "outdoor",
        "travel",
        "fitness",
        "jewelry",
        "accessories",
        "apparel",
        "footwear",
        "digital",
    }
)

HYGIENE_CATEGORIES = frozenset(
    {
        "beauty",
        "cosmetics",
        "personal_care",
        "hygiene",
    }
)

CATEGORY_LABELS = {
    "electronics": "Electronics",
    "apparel": "Clothing & Apparel",
    "home": "Home & Kitchen",
    "kitchen": "Home & Kitchen",
    "beauty": "Beauty & Cosmetics",
    "footwear": "Footwear",
    "grocery": "Grocery & Perishable Goods",
    "digital": "Digital Downloads",
    "fitness": "Physical Consumer Goods",
    "accessories": "Physical Consumer Goods",
    "jewelry": "Luxury Products",
    "books": "Books",
    "toys": "Toys & Games",
    "outdoor": "Physical Consumer Goods",
    "travel": "Physical Consumer Goods",
}


def product_type_label(category: str | None) -> str:
    normalized = (category or "unknown").lower()
    return CATEGORY_LABELS.get(normalized, normalized.replace("_", " ").title())


def is_hygiene_sensitive_product(item: OrderItem) -> bool:
    """Return whether opened-item hygiene restrictions apply to this product."""
    category = (item.category or "").lower()
    if category in NON_HYGIENE_CATEGORIES:
        return False
    if category in HYGIENE_CATEGORIES:
        return True
    return bool(item.hygiene_sensitive)
