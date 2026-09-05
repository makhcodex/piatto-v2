# Analysis of the old Piatto bot (v1) — the brief for the rebuild

A breakdown of the `telegram-order-bot` (v1) codebase, made before work on `piatto-v2` began. The goal is not to lose the old bot's functionality and not to repeat its architectural problems.

---

## 1. Project description

**Piatto** is a Telegram bot for ordering food from a restaurant/café (pizza, drinks, desserts). It implements the full cycle: browsing the catalogue → cart → placing the order → payment (manual confirmation of a card transfer) → tracking the order status. There is a separate admin panel for the owner: menu/category management, order processing, payment confirmation, statistics.

v1 is a monolith in a single Python process: aiogram (long polling) + PostgreSQL (SQLAlchemy async) + APScheduler in the same event loop. It was hosted on Railway as a worker process (no HTTP server).

---

## 2. Functionality — the user (customer)

- **`/start`** — a greeting (+ the logo, if `LOGO_URL` is set), creating/updating the user record, showing the reply keyboard: `📋 Catalogue | 🛒 Cart | ✅ Place order | 📦 My orders`.
- **`/cancel`** — cancelling the current FSM operation without clearing the cart.
- **`/restart`** — a full state reset.
- **Catalogue** → categories → products (photo, description, price, max quantity) → quick quantity choice (buttons 1/2/3/4 or "✏️ Custom quantity").
- **Cart** — stored in FSM memory only (not in the database!). Viewing, editing the quantity, removing a line, clearing the cart. The cart message is edited in place (it does not breed duplicates in the chat).
- **Placing an order** — 3 steps (name → phone validated by a regex → address, must contain a digit). Rate limit: 5 orders/hour/user. Before the order is created the cart is validated against the database again (availability, stock, current price, max quantity) — if something has changed, placing the order is blocked with an explanation.
- **Payment** — manual: the bot shows a static card number, the user presses "✅ I have paid", the admin confirms/rejects by hand through inline buttons. There is no real payment integration.
- **Reminders/auto-cancel** — through APScheduler: after 10 min a payment reminder, after 20 min an auto-cancel of the unpaid order.
- **"My orders"** — the customer's last 10 orders with details and status.
- Order statuses (linear): `pending → paid → preparing → delivering → delivered`, plus a separate terminal `cancelled_unpaid`.

## 3. Functionality — the admin

Access by a single hardcoded `ADMIN_ID` (there are no roles/access levels).

- **Active orders** — list, details, a "next status" button (along the linear chain), deleting an order (forbidden for `delivered`).
- **Order history** — pagination (10/page), filter by status.
- **Statistics** — order count, revenue, breakdown by status.
- **Products** — adding (5 steps: name → description → price → category → max quantity), editing fields, toggling "in stock", soft deletion.
- **Categories** — adding (slug + name), renaming, soft deletion (forbidden if there are products attached).
- **Confirming/rejecting a payment** — from the notification about the customer's claim.

## 4. Technical stack (v1)

| Component | Technology |
|---|---|
| Bot framework | aiogram 3.28.2, long polling (not webhook) |
| FSM/state | `MemoryStorage` — **in process memory, not persistent** |
| Database | PostgreSQL + SQLAlchemy 2.0 (async) + asyncpg |
| Scheduler | APScheduler (`AsyncIOScheduler`), **no persistent jobstore** |
| Hosting | Railway, a `worker` process, no HTTP port |
| Other | Supabase Storage (only for a one-off logo upload script), Google Sheets — declared in the README/dependencies, but **implemented nowhere** (a dead feature) |
| Tests | Absent as a framework; there are 2 ad-hoc simulation scripts with hand-written `assert`s, run manually against the real database |

### The data model (PostgreSQL, 5 tables)

- `categories` (id, slug, name, is_deleted)
- `users` (id, telegram_id, username, phone, created_at)
- `products` (id, name, category [a string, **not a real FK** to `categories.slug`], description, price, image_url, in_stock, max_quantity, is_deleted)
- `orders` (id, user_id→users FK, status [a string, not an enum], total_price, address, created_at, warning_sent, reminder_job_id, cancel_job_id)
- `order_items` (id, order_id FK, product_id FK, quantity, price [a snapshot of the price at the moment of the order])

There were no Alembic migrations — instead, `db/init_db.py` ran raw-SQL "safe migrations" on every start (`ADD COLUMN IF NOT EXISTS` inside try/except, converting a legacy Postgres enum → varchar, translating old RU product names to EN) and **unconditionally overwrote the prices of seed products** with the values from the code — meaning price edits made through the admin panel for those products were rolled back on every deploy.

---

## 5. v1's architectural problems (not to be repeated in v2)

1. **The cart and the scheduler jobs lived in process memory only.** Any restart/redeploy wiped every user's current cart and lost the scheduled reminders/auto-cancels of "stuck" orders. → v2 needs persistent state storage (a database or Redis).
2. **No real foreign keys** between `products.category` and `categories.slug` — just strings matching, so drift is possible.
3. **No migration system** (Alembic) — schema evolution through idempotent raw-SQL patches in the startup code, with errors swallowed (`except: pass`).
4. **A dangerous side effect in the seeding**: the prices of seed products were force-overwritten on every start, which killed the admin's manual price edits.
5. **Duplicated business logic**: the cart/quantity-limit calculation is duplicated in 3+ places (`menu.py`, `checkout.py`, `admin.py`) instead of a single service.
6. **UX messages and logic out of sync**: the "you can add N more" messages are left over from the old additive quantity logic, although the operation became an overwrite (a setter), not an increment.
7. **A single hardcoded admin** (`ADMIN_ID` in env) — no roles/multiple staff access.
8. **No real payment** — only a manually confirmed bank transfer; production would need a payment integration (Telegram Payments API / YooKassa / Stripe and the like).
9. **A declared but unimplemented feature** — synchronisation with Google Sheets (the dependencies and the documentation were there, the code was not).
10. **No automated tests** — only manual debug scripts, which mutated the real database at `DATABASE_URL`.
11. **Repository hygiene**: an uncommitted but present-in-the-root JSON key of a Google service account, log files and an accidental `=3.10.0` artefact from a mistyped pip command.
12. **Long polling assumes a single running instance** — the logs held traces of a conflict between several instances on one token (dev + prod at the same time).

---

## 6. A starting point for planning v2

Topics worth thinking through explicitly when designing the new architecture:

- Persistent cart/session storage (a database or Redis) instead of the in-memory FSM.
- A persistent jobstore for the scheduler (or moving reminders/auto-cancel into a separate worker with a database-backed queue).
- A proper migration system (Alembic) from day one.
- A real FK between products and categories.
- A single service for cart/limit calculation (removing the duplication).
- Roles/multiple staff access instead of a single `ADMIN_ID`.
- A real payment integration, or a deliberate decision to keep manual confirmation.
- Decide: is Google Sheets synchronisation needed at all, or does it leave the scope.
- Automated tests (pytest) from day one, without debug scripts mutating the production database.
