# CLAUDE.md — Piatto v2

Operational guide. Reasoning lives in `docs/architecture.md`; do not duplicate it here.

## Project

Telegram bot for food ordering at a single restaurant. Customers browse a catalogue,
build a cart, and place delivery orders inside Telegram; the admin manages the menu,
advances order status, and confirms payments by hand. Payment is manual bank transfer —
no payment gateway, ever. Stack: aiogram 3 (long polling) + PostgreSQL (SQLAlchemy async)
+ APScheduler in the same process. Deploys to Railway as a `worker`, one instance, no HTTP
port. This is a greenfield rewrite of `../telegram-order-bot` (v1), which is frozen and
must not be edited.

## Hard invariants

Never break these. A change that violates one is wrong even if tests pass.

1. **Layer direction is `handlers → services → db`, and `services → domain`.**
   Handlers never touch `session` and never compute anything. `domain/` calls nothing.
2. **`domain/` imports no framework.** No `aiogram`, `sqlalchemy`, `asyncpg`, `apscheduler`,
   and no `db`, `services`, or `handlers`. Enforced by `tests/domain/test_no_framework_imports.py`.
3. **Money is `Decimal`, always.** `Numeric(10, 2)` in the schema. `float()` must never
   appear near a price, total, or amount.
4. **Admin handlers live only under `handlers/admin/`.** Authorisation comes from router
   membership via `IsAdmin`, attached once in `handlers/admin/__init__.py`. Never add an
   admin callback to a customer router, and never write a per-handler admin check.
5. **The cart is `cart_items` in Postgres, quantity only.** No price column. Price is read
   live from `products`. FSM holds only the checkout wizard step.
6. **One price snapshot exists**: `order_items.price`, written once in
   `order_service.create_order`. It is immutable afterwards.
7. **`domain/` returns facts, not text.** No emoji, no HTML, no user-facing strings below
   `handlers/`.
8. **Unhandled exceptions propagate.** Services never swallow database errors. Unexpected
   exceptions (asyncpg failures, integrity errors) bubble up to aiogram's error handler.
   Only anticipated, per-item problems use `CartProblem`; everything else is a crash.

## File map

```
domain/              pure rules — no I/O, no async, no framework
  models.py          ProductView, CartLine, CartProblem (frozen dataclasses)
  pricing.py         line_total, cart_total -> Decimal
  cart_rules.py      check, apply, allowed_to_add

services/            owns the session, transactions, orchestration
  cart_service.py    cart CRUD; to_view/load_lines/resolve — the bridge into domain/
  order_service.py   create_order (snapshot + cart clear, one transaction),
                     status transitions, rate limit
  sweep.py           periodic payment reminder + auto-cancel, scheduler factory
  product_service.py product reads, admin CRUD
  category_service.py category reads, admin CRUD
  user_service.py    get_or_create(session, telegram_id) -> users.id (int, internal PK,
                     not telegram_id); every handler calls this first via the session user

handlers/            aiogram routers — I/O and rendering only
  __init__.py        build_router(); admin router included first
  render.py          CartProblem/CartLine -> text; the only place emoji live
  start.py menu.py cart.py checkout.py    customer flows, zero admin handlers
  notify.py          notify_user(bot, telegram_id, text); admin handlers delegate here
  admin/__init__.py  IsAdmin filter attached to the router
  admin/payments.py  confirm/reject payment
  admin/catalogue.py products and categories
  admin/orders.py    order list and status advancement

db/models.py         schema; OrderStatus enum, ACTIVE_STATUSES, NEXT_STATUS
db/engine.py         lazy engine + session factory, dispose_engine
db/middleware.py     DatabaseMiddleware injects data["session"] per update
keyboards/           ported from v1, depends on nothing
migrations/          Alembic; env.py reads DATABASE_URL from the environment
scripts/seed.py      standalone menu seed; `python -m scripts.seed` after migrations
config.py            env parsing; BOT_TOKEN, DATABASE_URL, ADMIN_IDS (frozenset[int]),
                     PAYMENT_CARD_NUMBER, LOGO_URL (optional), WARNING_MINUTES (10),
                     CANCEL_MINUTES (20), ORDER_RATE_LIMIT (5)
```

## Conventions

**Services return facts; handlers render them.**

- Recoverable, per-item problems: return `CartProblem` (or a list of them) alongside the
  result. Example: `added, problem = await cart_service.add(...)`.
- Whole-operation failure: raise a service exception carrying facts, e.g.
  `CartNotOrderable(problems)`. Handlers catch it and call `render.problems_text`.
- Never return a formatted string from a service. Never return an ORM row into a handler
  when a domain value would do.

**Sessions and transactions.** The middleware opens one session per update. Services commit;
handlers never do. Multi-write operations (`create_order`) commit once at the end and roll
back on exception.

**Adding to a cart is an addition.** Use `cart_rules.allowed_to_add` and add its return value
to the existing quantity. Never assign the requested quantity — that was v1's bug #6.

**Commit first, notify second.** A state change is committed before anyone is told about it,
and `bot.send_message` is always wrapped in try/except after the commit — see
`handlers/notify.notify_user` (used by admin handlers) and `sweep._notify` (intentional
duplication: the service layer must not import from handlers). A blocked user, a deleted chat,
or a Telegram outage must never roll back a status the database already accepted.

**Sweep timings.** `WARNING_MINUTES` and `CANCEL_MINUTES` come from `config.py`
(defaults: 10 and 20). The sweep interval is `SWEEP_INTERVAL_SECONDS` (default 60, from
config.py). These three numbers are the only place timing lives — handlers and services
read them from config, never hardcode.

**Rate limit.** `create_order` enforces a per-user limit of `ORDER_RATE_LIMIT` orders
per hour (default: 5, from `config.py`). The service raises `RateLimitExceeded`; the
handler catches it and shows a message. The limit is checked in the service, not in the
handler.

**FSM holds the checkout wizard state: current step AND already-entered fields** (name,
phone, address). It does not hold cart data, product info, or anything that survives a
restart. Loss of FSM state mid-checkout is acceptable — the user restarts the wizard,
the cart in Postgres is untouched.

**Admin wizards (`handlers/admin/catalogue_states.py`) hold the step plus the id being
edited and the fields already typed — never an ORM row.** Every wizard is escapable with
`/cancel`, and every admin command clears state before starting, so an abandoned wizard
cannot swallow later messages.

**Keyboards depend on nothing and nothing depends on them.** They take primitives or
domain values, never a session; v1 ports are kept verbatim, new ones are written for v2.

**Callback data is `subsystem:action:id`.** A subsystem prefix may be split across the
admin and customer routers only if the action segments are disjoint — the admin router
is included first and will shadow anything it matches.

**Within a router, handlers are matched in registration order.** A `/cancel` (or any
escape hatch) must be declared before the state handlers it rescues, or the state handler
matches first and the wizard has no exit.

**A service read that hides soft-deleted rows keeps the plain name; the admin counterpart
is suffixed `_for_admin`.** Never change the visibility semantics of an existing name.

**A rule that a wizard must apply mid-flight lives in the service as a public `check_*`
function.** The handler parses input and calls it; the rule still exists exactly once.

**Naming.** Services are verbs on the domain (`create_order`, `set_status`, `resolve`).
Comments and code are English; `docs/` and `README.md` are Russian.

## Tests

```bash
pytest tests/domain          # no database, no drivers, ~0.1s
pytest                       # full suite; service tests skip without TEST_DATABASE_URL
```

Must stay green:

- **30 domain tests** in `tests/domain/`. They run with nothing but `pytest` installed —
  if they start needing a driver or an event loop, the boundary has leaked.
- **`test_no_framework_imports.py`** — the only architectural rule a machine enforces.

Never put database fixtures in `tests/conftest.py`; they belong in `tests/services/conftest.py`.
Service tests use a session inside a transaction that is rolled back per test.

## Startup

```bash
alembic upgrade head    # separate step, before the process starts; not run by main.py
python main.py
```

`main.py` sequence: validate `BOT_TOKEN`, `ADMIN_IDS` and `PAYMENT_CARD_NUMBER` (any of them
empty aborts — with no admin nobody could confirm a payment, with no card number nobody could
make one, and the sweep would auto-cancel every order after `CANCEL_MINUTES`) → `Bot` with
HTML parse mode → `Dispatcher` with `MemoryStorage` →
`DatabaseMiddleware` → `build_router()` → `create_scheduler(bot).start()` →
`delete_webhook(drop_pending_updates=True)` → `start_polling`. Shutdown always runs
`scheduler.shutdown`, `bot.session.close`, `dispose_engine`.

## Status

**Implemented and working:** `domain/`, `db/`, `config.py`, `main.py`, `keyboards/`,
`scripts/seed.py`; all of `services/`, admin CRUD included; every customer
handler (`start`, `menu`, `cart`, `checkout`); `handlers/render.py`, `handlers/__init__.py`;
and the admin surface — `admin/__init__.py`, `admin/payments.py` (`pay:` callbacks),
`admin/orders.py` (`order:` callbacks: active list, detail, advance), `admin/catalogue.py`
(`prod:` and `ctg:` callbacks: product and category CRUD, FSM wizards in
`admin/catalogue_states.py`). `tests/domain/` is 30 passing.

Migrations: `00ba32237596` creates all six tables (`down_revision = None`), `a1c4f9e27b30`
adds `uq_products_name`. New schema changes go in a migration on top of the chain, never
by editing an existing one.

**Not written yet:** `tests/services/` — every test skips with `TODO`. That is the whole
remaining backlog.

**Seeding.** `scripts/seed.py` is standalone and never called from `main.py`. It upserts
through `category_service.upsert` and `product_service.upsert_seed`, keyed on
`categories.slug` and `uq_products_name`. `upsert_seed` writes `price` on INSERT only and
omits it from DO UPDATE SET — a re-seed must never undo a price the admin edited in the
bot. Do not add `price` to that set clause.
