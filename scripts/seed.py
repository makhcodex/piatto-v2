"""Seed the initial menu. Standalone — never called from main.py.

Run after migrations, from the repository root:

    alembic upgrade head
    python -m scripts.seed

Idempotent. Re-running refreshes names, descriptions, categories and limits, and
un-deletes anything soft-deleted, but never touches the price of a product that
already exists. Prices are the admin's to edit in the bot; v1 overwrote them on
every startup, which is the bug this rule exists to prevent.

To change a seed price deliberately, edit it in the bot, not here.
"""

import asyncio
import logging
from decimal import Decimal

from db.engine import dispose_engine, get_session_factory
from services import category_service, product_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed")

CATEGORIES = [
    {"slug": "pizza", "name": "🍕 Pizza"},
    {"slug": "drinks", "name": "🥤 Drinks"},
    {"slug": "desserts", "name": "🍰 Desserts"},
]

PRODUCTS = [
    {
        "category": "pizza",
        "name": "Margherita",
        "price": Decimal("12.50"),
        "max_quantity": 20,
        "description": "Tomato sauce, mozzarella, basil",
    },
    {
        "category": "pizza",
        "name": "Pepperoni",
        "price": Decimal("14.50"),
        "max_quantity": 15,
        "description": "Pepperoni, mozzarella, tomato sauce",
    },
    {
        "category": "pizza",
        "name": "Four Cheese",
        "price": Decimal("15.00"),
        "max_quantity": 15,
        "description": "Mozzarella, cheddar, gouda, parmesan",
    },
    {
        "category": "drinks",
        "name": "Cola 0.5L",
        "price": Decimal("1.99"),
        "max_quantity": 50,
        "description": "Coca-Cola 0.5L",
    },
    {
        "category": "drinks",
        "name": "Fanta 0.33L",
        "price": Decimal("1.49"),
        "max_quantity": 50,
        "description": "Fanta Orange 0.33L",
    },
    {
        "category": "drinks",
        "name": "Water 0.5L",
        "price": Decimal("1.49"),
        "max_quantity": 100,
        "description": "Still mineral water",
    },
    {
        "category": "drinks",
        "name": "Orange Juice",
        "price": Decimal("2.49"),
        "max_quantity": 30,
        "description": "100% natural orange juice",
    },
    {
        "category": "desserts",
        "name": "Tiramisu",
        "price": Decimal("6.50"),
        "max_quantity": 10,
        "description": "Classic Italian dessert",
    },
    {
        "category": "desserts",
        "name": "Cheesecake",
        "price": Decimal("5.50"),
        "max_quantity": 10,
        "description": "New York style cheesecake",
    },
    {
        "category": "desserts",
        "name": "Brownie",
        "price": Decimal("4.50"),
        "max_quantity": 20,
        "description": "Chocolate brownie",
    },
]


async def seed() -> None:
    async with get_session_factory()() as session:
        category_ids: dict[str, int] = {}
        for category in CATEGORIES:
            category_ids[category["slug"]] = await category_service.upsert(
                session, slug=category["slug"], name=category["name"]
            )
        logger.info("categories: %d upserted", len(category_ids))

        inserted = 0
        refreshed = 0
        for product in PRODUCTS:
            slug = product["category"]
            if slug not in category_ids:
                raise ValueError(f"{product['name']!r} references unknown category {slug!r}")

            _, was_inserted = await product_service.upsert_seed(
                session,
                category_id=category_ids[slug],
                name=product["name"],
                price=product["price"],
                description=product["description"],
                max_quantity=product["max_quantity"],
            )
            if was_inserted:
                inserted += 1
            else:
                refreshed += 1

        logger.info("products: %d inserted, %d refreshed (prices left untouched)",
                    inserted, refreshed)


async def main() -> None:
    try:
        await seed()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
