"""Menu management: products and categories.

Callback data, `subsystem:action:id`, with two subsystems that collide with nothing
the customer routers own (`category:`, `item:`, `qty:`, `cart:`, `order:`, `pay:`):

    prod:list                prod:detail:{id}    prod:stock:{id}    prod:del:{id}
    prod:price:{id}          prod:qty:{id}       prod:add           prod:setcat:{id}
    ctg:list                 ctg:detail:{id}     ctg:rename:{id}    ctg:del:{id}
    ctg:add

`prod:`, not `cat:`: `cat:` sitting next to the customer's `category:` reads as the
same subsystem and is not.

Validation has one owner. The handler parses text and picks the words;
`product_service.check_price` / `check_quantity` hold the rules, and the wizard calls
them at the step where the value was typed so the verdict is not three steps late.

Registration order matters inside a router: /cancel is declared before every state
handler, or the state handler would eat it and the wizard would have no exit.
"""

import logging
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Category, Product
from handlers import render
from handlers.admin.catalogue_states import AddCategory, AddProduct, EditCategory, EditProduct
from keyboards.admin_catalogue import (
    get_categories_keyboard,
    get_category_detail_keyboard,
    get_category_pick_keyboard,
    get_product_detail_keyboard,
    get_products_keyboard,
)
from keyboards.main_menu import MENU_TEXTS
from services import category_service, product_service

logger = logging.getLogger(__name__)

router = Router(name="admin.catalogue")

WIZARDS = (AddProduct, EditProduct, AddCategory, EditCategory)

NAME_MAX = 128
SLUG_MAX = 32
CATEGORY_NAME_MAX = 64
SKIP = "-"

NO_PRODUCTS = "Товаров пока нет."
NO_CATEGORIES = "Категорий пока нет. Добавьте первую: /add_category"
PRODUCT_GONE = "Товар не найден"
CATEGORY_GONE = "Категория не найдена"
NEED_CATEGORY = "Сначала создайте категорию: /add_category"
CANCELLED = "Отменено."
STALE = "Мастер сброшен — начните заново."
ABORT_HINT = "Отправьте /cancel, чтобы прервать."
PICK_BUTTON = "Выберите категорию кнопкой выше."

BAD_NAME = f"❌ Название: 1–{NAME_MAX} символов. Ещё раз:"
NAME_TAKEN = "❌ Товар с таким именем уже есть. Введите другое:"
BAD_PRICE = "❌ Цена — положительное число, например 9.50. Ещё раз:"
BAD_QUANTITY = "❌ Максимум в заказе — целое число от 1. Ещё раз:"
BAD_SLUG = f"❌ Slug: латиница, цифры и дефис, до {SLUG_MAX} символов. Ещё раз:"
SLUG_TAKEN = "❌ Категория с таким slug уже есть. Введите другой:"
BAD_CATEGORY_NAME = f"❌ Название: 1–{CATEGORY_NAME_MAX} символов. Ещё раз:"

ASK_NAME = "✏️ Название товара?"
ASK_DESCRIPTION = f"📝 Описание? Отправьте {SKIP}, чтобы пропустить."
ASK_PRICE = "💰 Цена? Например 9.50"
ASK_CATEGORY = "📂 Категория?"
ASK_QUANTITY = "📦 Максимум штук в одном заказе?"
ASK_SLUG = "🔤 Slug категории (латиницей, например pizza)?"
ASK_CATEGORY_NAME = "✏️ Отображаемое название категории?"
ASK_NEW_NAME = "✏️ Новое название категории?"


# ── Escape hatch — must be registered before any state handler ────────────────


@router.message(Command("cancel"), StateFilter(*WIZARDS))
async def cancel_wizard(message: Message, state: FSMContext) -> None:
    """Without this a half-finished wizard eats every message the admin sends."""
    await state.clear()
    await message.answer(CANCELLED)


# ── Products ──────────────────────────────────────────────────────────────────


@router.message(Command("products"))
async def cmd_products(message: Message, state: FSMContext, session: AsyncSession) -> None:
    # Opening a list abandons an unfinished wizard rather than leaving it armed.
    await state.clear()
    text, keyboard = await _products_view(session)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "prod:list")
async def products_list(callback: CallbackQuery, session: AsyncSession) -> None:
    await _show(callback, *await _products_view(session))
    await callback.answer()


@router.callback_query(F.data.startswith("prod:detail:"))
async def product_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    await _refresh_product(callback, session, _arg(callback))


@router.callback_query(F.data.startswith("prod:stock:"))
async def product_toggle_stock(callback: CallbackQuery, session: AsyncSession) -> None:
    product = await product_service.toggle_in_stock(session, _arg(callback))
    if product is None:
        await callback.answer(PRODUCT_GONE, show_alert=True)
        return

    logger.info(
        "Product #%d in_stock -> %s by admin %s",
        product.id, product.in_stock, callback.from_user.id,
    )
    await _refresh_product(
        callback, session, product.id, "В наличии" if product.in_stock else "Убрано из наличия"
    )


@router.callback_query(F.data.startswith("prod:del:"))
async def product_toggle_deleted(callback: CallbackQuery, session: AsyncSession) -> None:
    product = await product_service.toggle_deleted(session, _arg(callback))
    if product is None:
        await callback.answer(PRODUCT_GONE, show_alert=True)
        return

    logger.info(
        "Product #%d is_deleted -> %s by admin %s",
        product.id, product.is_deleted, callback.from_user.id,
    )
    await _refresh_product(
        callback, session, product.id, "Удалён" if product.is_deleted else "Восстановлен"
    )


@router.callback_query(F.data.startswith("prod:price:"))
async def product_ask_price(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditProduct.waiting_for_price)
    await state.update_data(product_id=_arg(callback))
    await callback.answer()
    await callback.message.answer(f"{ASK_PRICE}\n{ABORT_HINT}")


@router.message(EditProduct.waiting_for_price, ~F.text.in_(MENU_TEXTS))
async def product_set_price(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    price = _parse_price(message.text)
    if price is None:
        await message.answer(BAD_PRICE)
        return

    product_id = await _take(state, "product_id")
    if product_id is None:
        await message.answer(STALE)
        return

    product = await product_service.update_price(session, product_id, price)
    if product is None:
        await message.answer(PRODUCT_GONE)
        return

    logger.info("Product #%d price -> %s by admin %s", product.id, price, message.from_user.id)
    await _answer_product(message, session, product.id)


@router.callback_query(F.data.startswith("prod:qty:"))
async def product_ask_quantity(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditProduct.waiting_for_max_quantity)
    await state.update_data(product_id=_arg(callback))
    await callback.answer()
    await callback.message.answer(f"{ASK_QUANTITY}\n{ABORT_HINT}")


@router.message(EditProduct.waiting_for_max_quantity, ~F.text.in_(MENU_TEXTS))
async def product_set_quantity(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    quantity = _parse_quantity(message.text)
    if quantity is None:
        await message.answer(BAD_QUANTITY)
        return

    product_id = await _take(state, "product_id")
    if product_id is None:
        await message.answer(STALE)
        return

    product = await product_service.update_max_quantity(session, product_id, quantity)
    if product is None:
        await message.answer(PRODUCT_GONE)
        return

    logger.info(
        "Product #%d max_quantity -> %d by admin %s",
        product.id, quantity, message.from_user.id,
    )
    await _answer_product(message, session, product.id)


# ── Add product wizard ────────────────────────────────────────────────────────


@router.message(Command("add_product"))
async def cmd_add_product(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _start_add_product(message, state, session)


@router.callback_query(F.data == "prod:add")
async def start_add_product(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await callback.answer()
    await _start_add_product(callback.message, state, session)


async def _start_add_product(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    # A product needs a category: products.category_id is a non-null FK.
    if not await category_service.list_all(session):
        await message.answer(NEED_CATEGORY)
        return
    await state.set_state(AddProduct.waiting_for_name)
    await message.answer(f"{ASK_NAME}\n{ABORT_HINT}")


@router.message(AddProduct.waiting_for_name, ~F.text.in_(MENU_TEXTS))
async def add_product_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= NAME_MAX:
        await message.answer(BAD_NAME)
        return
    # uq_products_name would raise on insert; asked here instead of crashed there.
    if await product_service.name_taken(session, name):
        await message.answer(NAME_TAKEN)
        return

    await state.update_data(name=name)
    await state.set_state(AddProduct.waiting_for_description)
    await message.answer(ASK_DESCRIPTION)


@router.message(AddProduct.waiting_for_description, ~F.text.in_(MENU_TEXTS))
async def add_product_description(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    await state.update_data(description=None if raw == SKIP else raw)
    await state.set_state(AddProduct.waiting_for_price)
    await message.answer(ASK_PRICE)


@router.message(AddProduct.waiting_for_price, ~F.text.in_(MENU_TEXTS))
async def add_product_price(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    price = _parse_price(message.text)
    if price is None:
        await message.answer(BAD_PRICE)
        return

    categories = await category_service.list_all(session)
    if not categories:
        await state.clear()
        await message.answer(NEED_CATEGORY)
        return

    # str, not Decimal: FSM data has to survive a storage that only speaks JSON.
    await state.update_data(price=str(price))
    await state.set_state(AddProduct.waiting_for_category)
    await message.answer(ASK_CATEGORY, reply_markup=_category_pick(categories))


@router.callback_query(AddProduct.waiting_for_category, F.data.startswith("prod:setcat:"))
async def add_product_category(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(category_id=_arg(callback))
    await state.set_state(AddProduct.waiting_for_max_quantity)
    await callback.answer()
    await callback.message.answer(ASK_QUANTITY)


@router.message(AddProduct.waiting_for_category, ~F.text.in_(MENU_TEXTS))
async def add_product_category_nudge(message: Message) -> None:
    await message.answer(PICK_BUTTON)


@router.message(AddProduct.waiting_for_max_quantity, ~F.text.in_(MENU_TEXTS))
async def add_product_quantity(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    quantity = _parse_quantity(message.text)
    if quantity is None:
        await message.answer(BAD_QUANTITY)
        return

    data = await state.get_data()
    await state.clear()
    if not {"name", "price", "category_id"} <= data.keys():
        await message.answer(STALE)
        return

    product = await product_service.create(
        session,
        category_id=data["category_id"],
        name=data["name"],
        price=Decimal(data["price"]),
        description=data.get("description"),
        max_quantity=quantity,
    )
    logger.info("Product #%d created by admin %s", product.id, message.from_user.id)
    await message.answer(f"✅ Товар добавлен: <b>{product.name}</b>")
    await _answer_product(message, session, product.id)


# ── Categories ────────────────────────────────────────────────────────────────


@router.message(Command("categories"))
async def cmd_categories(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    text, keyboard = await _categories_view(session)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "ctg:list")
async def categories_list(callback: CallbackQuery, session: AsyncSession) -> None:
    await _show(callback, *await _categories_view(session))
    await callback.answer()


@router.callback_query(F.data.startswith("ctg:detail:"))
async def category_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    await _refresh_category(callback, session, _arg(callback))


@router.callback_query(F.data.startswith("ctg:del:"))
async def category_toggle_deleted(callback: CallbackQuery, session: AsyncSession) -> None:
    category_id = _arg(callback)

    category = await category_service.toggle_deleted(session, category_id)
    if category is None:
        # Two reasons to refuse. The count is what tells them apart.
        live = await product_service.count_in_category(session, category_id)
        await callback.answer(
            f"Нельзя скрыть: в категории {live} активных товаров" if live else CATEGORY_GONE,
            show_alert=True,
        )
        return

    logger.info(
        "Category #%d is_deleted -> %s by admin %s",
        category.id, category.is_deleted, callback.from_user.id,
    )
    await _refresh_category(
        callback, session, category.id, "Скрыта" if category.is_deleted else "Восстановлена"
    )


@router.callback_query(F.data.startswith("ctg:rename:"))
async def category_ask_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditCategory.waiting_for_name)
    await state.update_data(category_id=_arg(callback))
    await callback.answer()
    await callback.message.answer(f"{ASK_NEW_NAME}\n{ABORT_HINT}")


@router.message(EditCategory.waiting_for_name, ~F.text.in_(MENU_TEXTS))
async def category_set_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= CATEGORY_NAME_MAX:
        await message.answer(BAD_CATEGORY_NAME)
        return

    category_id = await _take(state, "category_id")
    if category_id is None:
        await message.answer(STALE)
        return

    category = await category_service.rename(session, category_id, name)
    if category is None:
        await message.answer(CATEGORY_GONE)
        return

    logger.info("Category #%d renamed by admin %s", category.id, message.from_user.id)
    await _answer_category(message, session, category.id)


# ── Add category wizard ───────────────────────────────────────────────────────


@router.message(Command("add_category"))
async def cmd_add_category(message: Message, state: FSMContext) -> None:
    await _start_add_category(message, state)


@router.callback_query(F.data == "ctg:add")
async def start_add_category(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _start_add_category(callback.message, state)


async def _start_add_category(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddCategory.waiting_for_slug)
    await message.answer(f"{ASK_SLUG}\n{ABORT_HINT}")


@router.message(AddCategory.waiting_for_slug, ~F.text.in_(MENU_TEXTS))
async def add_category_slug(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    slug = (message.text or "").strip().lower()
    if not _is_slug(slug):
        await message.answer(BAD_SLUG)
        return
    if await category_service.slug_taken(session, slug):
        await message.answer(SLUG_TAKEN)
        return

    await state.update_data(slug=slug)
    await state.set_state(AddCategory.waiting_for_name)
    await message.answer(ASK_CATEGORY_NAME)


@router.message(AddCategory.waiting_for_name, ~F.text.in_(MENU_TEXTS))
async def add_category_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= CATEGORY_NAME_MAX:
        await message.answer(BAD_CATEGORY_NAME)
        return

    slug = await _take(state, "slug")
    if slug is None:
        await message.answer(STALE)
        return

    category = await category_service.create(session, slug=slug, name=name)
    logger.info("Category #%d created by admin %s", category.id, message.from_user.id)
    await message.answer(f"✅ Категория добавлена: <b>{category.name}</b>")
    await _answer_category(message, session, category.id)


# ── Views ─────────────────────────────────────────────────────────────────────


async def _products_view(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    products = await product_service.list_for_admin(session)
    if not products:
        return NO_PRODUCTS, None

    lines: list[str] = []
    group = None
    for product in products:
        # Ordered by category name in the service, so a change of name starts a group.
        if product.category.name != group:
            group = product.category.name
            lines.append(f"\n<b>{group}</b>")
        lines.append(f"{_flag(product)} {product.name} — {render.money(product.price)}")

    text = f"📦 <b>Товары</b> ({len(products)})\n" + "\n".join(lines)
    rows = [(p.id, p.name, p.in_stock, p.is_deleted) for p in products]
    return text, get_products_keyboard(rows)


async def _product_view(
    session: AsyncSession, product_id: int
) -> tuple[str, InlineKeyboardMarkup] | None:
    product = await product_service.get_for_admin(session, product_id)
    if product is None:
        return None
    return (
        _product_text(product),
        get_product_detail_keyboard(product.id, product.in_stock, product.is_deleted),
    )


def _product_text(product: Product) -> str:
    return (
        f"{_flag(product)} <b>{product.name}</b>\n"
        f"Категория: {product.category.name}\n"
        f"Цена: {render.money(product.price)}\n"
        f"Максимум в заказе: {product.max_quantity}\n"
        f"В наличии: {'да' if product.in_stock else 'нет'}\n"
        f"Статус: {'удалён' if product.is_deleted else 'активен'}\n\n"
        f"📝 {product.description or '—'}"
    )


def _flag(product: Product) -> str:
    if product.is_deleted:
        return "🚫"
    return "✅" if product.in_stock else "❌"


async def _categories_view(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    categories = await category_service.list_for_admin(session)
    if not categories:
        return NO_CATEGORIES, None

    rows = "\n".join(
        f"{'🚫' if c.is_deleted else '✅'} <b>{c.name}</b> — <code>{c.slug}</code>"
        for c in categories
    )
    text = f"📂 <b>Категории</b> ({len(categories)})\n\n{rows}"
    return text, get_categories_keyboard([(c.id, c.name, c.is_deleted) for c in categories])


async def _category_view(
    session: AsyncSession, category_id: int
) -> tuple[str, InlineKeyboardMarkup] | None:
    category = await category_service.get(session, category_id)
    if category is None:
        return None

    live = await product_service.count_in_category(session, category.id)
    text = (
        f"{'🚫' if category.is_deleted else '✅'} <b>{category.name}</b>\n"
        f"Slug: <code>{category.slug}</code>\n"
        f"Активных товаров: {live}\n"
        f"Статус: {'скрыта' if category.is_deleted else 'активна'}"
    )
    return text, get_category_detail_keyboard(category.id, category.is_deleted)


def _category_pick(categories: list[Category]) -> InlineKeyboardMarkup:
    return get_category_pick_keyboard([(c.id, c.name) for c in categories])


# ── Plumbing ──────────────────────────────────────────────────────────────────


def _arg(callback: CallbackQuery) -> int:
    """The id — last segment of `subsystem:action:id`."""
    return int(callback.data.rsplit(":", 1)[1])


async def _take(state: FSMContext, key: str):
    """Read one FSM field and end the step. None means the wizard went stale."""
    value = (await state.get_data()).get(key)
    await state.clear()
    return value


def _parse_price(raw: str | None) -> Decimal | None:
    """Parse; let the service judge. None means "say BAD_PRICE and ask again"."""
    try:
        price = Decimal((raw or "").strip().replace(",", "."))
        product_service.check_price(price)
    except (InvalidOperation, ValueError):
        return None
    return price


def _parse_quantity(raw: str | None) -> int | None:
    try:
        quantity = int((raw or "").strip())
        product_service.check_quantity(quantity)
    except ValueError:
        return None
    return quantity


def _is_slug(slug: str) -> bool:
    # Format only. Uniqueness is a database question, asked separately.
    return bool(slug) and len(slug) <= SLUG_MAX and all(
        char.isascii() and (char.isalnum() or char == "-") for char in slug
    )


async def _show(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None
) -> None:
    """Render in place; fall back to a new message when the old one cannot be edited."""
    message = callback.message
    if not isinstance(message, Message):
        return
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        # Identical content, or a message too old to edit.
        await message.answer(text, reply_markup=keyboard)


async def _refresh_product(
    callback: CallbackQuery, session: AsyncSession, product_id: int, note: str = ""
) -> None:
    view = await _product_view(session, product_id)
    if view is None:
        await callback.answer(PRODUCT_GONE, show_alert=True)
        return
    await callback.answer(note)
    await _show(callback, *view)


async def _refresh_category(
    callback: CallbackQuery, session: AsyncSession, category_id: int, note: str = ""
) -> None:
    view = await _category_view(session, category_id)
    if view is None:
        await callback.answer(CATEGORY_GONE, show_alert=True)
        return
    await callback.answer(note)
    await _show(callback, *view)


async def _answer_product(message: Message, session: AsyncSession, product_id: int) -> None:
    """After a text step there is no inline message to edit — send a fresh one."""
    view = await _product_view(session, product_id)
    if view is None:
        await message.answer(PRODUCT_GONE)
        return
    text, keyboard = view
    await message.answer(text, reply_markup=keyboard)


async def _answer_category(message: Message, session: AsyncSession, category_id: int) -> None:
    view = await _category_view(session, category_id)
    if view is None:
        await message.answer(CATEGORY_GONE)
        return
    text, keyboard = view
    await message.answer(text, reply_markup=keyboard)
