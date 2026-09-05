# Piatto v2 — architecture (decisions locked in)

Source: the v1 analysis in `.claude/plans/majestic-strolling-nest.md`.
Stress test of the draft and the reasoning behind the decisions: `.claude/plans/grill-me-docs-architecture-draft-md-kind-rocket.md`.

All eight branches are closed. Below is the accepted architecture, without code.

## Constraints

- One restaurant, one deployment, one developer. No multi-tenancy, neither in the schema nor in the permissions.
- Payments — manual transfer confirmation only. Telegram Payments and external gateways are excluded.
- Railway stays a `worker` process, long polling, no HTTP port.
- **v1 is not developed further.** It is frozen and stays running until the switchover.

## Transition strategy (branch 1)

**Greenfield.** A new repository `piatto-v2`, next to v1. Only `keyboards/*` and `config.py` are carried over as they are, everything else is written again.

The key fact that removed the main risk: **v1 has no real customers** — only the developer and test users. Hence:

- no data migration is needed, v2 has its own clean database;
- no parity test suite against v1 is needed;
- rollback is trivial — point the token back at v1;
- the switchover criterion is "v2 passes the happy path", not "v2 matches v1 on every scenario".

## Layers and boundaries

```
handlers/   aiogram routers: I/O and keyboard rendering only
      ↓
services/   database work, transactions, orchestration
      ↓
db/         SQLAlchemy models, engine, migrations

domain/     pure rules: no aiogram, no sqlalchemy
      ↑     called from services/, calls nothing itself
```

`keyboards/*` is a pure UI layer, it depends on nobody.

The rule: a handler does not touch `session` and computes nothing itself — only a service call.

### `domain/` — the one boundary a machine guards (branch 5)

```
domain/
  models.py      frozen dataclasses CartLine, CartProblem
  pricing.py     cart_total(lines) -> Decimal
  cart_rules.py  check(lines) -> list[CartProblem]
```

Inside `domain/`, imports of `aiogram` and `sqlalchemy` are forbidden. The ban is checked by a test that reads the imports of the package's modules and fails on a violation.

This was chosen over `services/pricing.py` deliberately: pure functions inside `services/` would sit in the same import graph as `order_service.py`, which has a session by definition, and the boundary would again rest on discipline alone — exactly what fell apart in v1.

Dataclasses instead of dictionaries pin the shape of the cart down in one place. In v1 the shape is pinned nowhere, hence its three different representations.

**Consequence:** the rules return typed `CartProblem` values, not finished strings. Text and emoji are drawn by the handler. In v1 it is the other way round — `validate_cart` returns HTML with emoji straight out of the service (`order_service.py:50-71`), which makes the logic non-reusable.

The flow of one request:

```
handlers/menu.py           user_id from the callback, service call
      ↓
services/cart_service.py   SELECT products, assembling list[CartLine]
      ↓
domain/cart_rules.py       check(lines) -> [CartProblem(...)]
domain/pricing.py          cart_total(lines) -> Decimal
      ↓
services/cart_service.py   applying, commit
      ↓
handlers/menu.py           CartProblem -> text with emoji, sending
```

## Where the state lives

### The cart — a table, quantity only (branch 2)

```
cart_items(user_id, product_id, qty)   UNIQUE(user_id, product_id)
```

**There is no price column.** The price is always read live from `products` when displaying and totalling. The snapshot is taken once, at order creation — into `order_items.price` — and it is immutable.

Reasoning: the price snapshot is the sole reason the price-reconciliation branch exists in `validate_cart` (`order_service.py:58-64`), which compares the stored price with the current one, writes a warning and mutates the incoming dictionary. Without a stored price that state cannot arise — the code is not rewritten, it is deleted.

Three checks remain: the product is deleted, it is out of stock, the quantity is above `max_quantity`.

The accepted trade-off: a price change between adding to the cart and paying happens silently. Justified by scale — price edits are rare and deliberate, and one person makes them.

### FSM

`MemoryStorage` stays, but is used only for the short-lived step of the checkout wizard — which field the user is entering right now. Losing the step on a restart is not critical: the cart is in the database and does not suffer.

The v1 idiom "`state.clear()`, then restore the cart by hand" (more than 20 places) disappears along with the cart in the FSM.

### Jobs — a sweep instead of date triggers (branch 3)

One APScheduler interval job every 60 seconds instead of two date jobs per order:

```
every 60 s:
  overdue warnings → notify, warning_sent = True
  overdue payments → CANCELLED_UNPAID, notify
```

It uses `get_orders_pending_warning` (`order_service.py:236`) and `get_orders_to_auto_cancel` (`:252`), already written in v1 and never called there.

In the schema: `orders.warning_sent` stays and is finally written to; `reminder_job_id` and `cancel_job_id` are not carried over into v2.

What settled it in favour of the sweep:

- v1's jobs already re-read the order from the database and bail out when the status has changed (`scheduler.py:33`, `:55`) — that is, they are already idempotent, and the database is the authority; that is exactly the property the sweep approach requires;
- `schedule_order_jobs` passes a live `Bot` object in kwargs (`scheduler.py:91`, `:99`) — it does not serialise, and a persistent jobstore would require rewriting the job signatures;
- `SQLAlchemyJobStore` is synchronous only — it would mean keeping a second, synchronous engine next to the async one;
- the state lives in `orders`, not in a separate jobs table, so drift between the two is impossible, and a restart is survived without any persistence at all.

The trade-off: firing accuracy of ±60 seconds.

## Access control (branch 4)

**`ADMIN_IDS: set[int]`** from an environment variable. A `staff` table was rejected: a schema, CRUD handlers and a bootstrap problem for the sake of a one-element set that does not change.

**The main thing in this branch is the structural decision:** authorisation becomes a property of router membership. Every admin handler sits on the admin router under the `IsAdmin` filter; the customer routers hold no admin handler at all. The check cannot be forgotten in an individual handler — it cannot fail to be inherited.

Concretely: confirming and rejecting a payment live in `handlers/admin/payments.py`, not in `checkout.py`.

### 🔴 The hole in v1 that this fixes

`admin_confirm_payment` (`checkout.py:320-321`) and `admin_reject_payment` (`:361`) are registered on the **checkout** router, while `IsAdmin` is attached only to the `admin.py` router (`admin.py:46-47`). There is no check of its own in the body — the handler goes straight into `update_order_status(..., PAID)` (`:335`).

Any user who sends the matching callback data marks **any** order paid.

v1 is not being fixed (there are no real customers, the hole stays in the frozen code). Here it is recorded as a requirement for v2.

## Money (branch 7)

**`Decimal` + `Numeric(10, 2)`** end to end. The v1 schema is already like that in all three places (`models.py:76, 97, 115`), SQLAlchemy hands back `Decimal` without conversion.

Every float in v1 is corruption on the handler side: `float(db_p.price)` (`order_service.py:58`), float collapses in `menu.py:70-78` and `checkout.py:33-39`. In a greenfield those places are simply never written.

The rule: `float()` appears nowhere near money. `domain/` accepts and returns `Decimal` only.

Integer cents were considered and rejected — more reliable, but they require conversion at every rendering and admin-input boundary, and the prices are whole euros anyway.

## The database schema — what gets fixed relative to v1

- `products.category_id` — a **real FK** to `categories.id`. In v1 the link rests on the strings `Product.category` and `Category.slug` matching, through `primaryjoin` (`models.py:52-54`, `:82-87`).
- `orders.status` — an **enum** instead of a `String(20)` string.
- `cart_items` — a new table (branch 2).
- `orders.reminder_job_id` / `cancel_job_id` — **not carried over** (branch 3).
- Migrations — **Alembic from scratch**, instead of raw-SQL patches with `except: pass` in `db/init_db.py`.
- The seed does not overwrite the prices of existing products on every start.

## Google Sheets (branch 6)

**Drop it entirely.** v2 has no dependencies (`gspread`, `google-auth`, `google-auth-oauthlib`, `requests-oauthlib`), no `GOOGLE_*` variables and no mentions in the README. No service account is needed.

The feature lived through the whole of v1 as four dependencies, five mentions in the README and one leaked key — at zero lines of code. With one restaurant, the admin order list inside the bot covers the same need. Dropping it removes an entire class of failure (an external API being unavailable at the moment an order is created) and one surface for leaking secrets.

## Tests (branch 8)

```
tests/
  domain/                      no database, no async, milliseconds
    test_pricing.py
    test_cart_rules.py
    test_no_framework_imports.py
  services/                    a real Postgres
    test_cart_service.py
    test_order_service.py
    test_sweep.py
```

The service-layer fixture: a session inside a transaction, rolled back after every test.

Handlers are not tested automatically — once the rules moved into `domain/`, no logic worth catching is left in them. Before a run the happy path is checked by hand once.

The integration layer is mandatory: the sweep job, the cart in a table and `Numeric(10,2)` are database behaviour, and unit tests do not catch it. That is precisely where v2's new risk is concentrated.

Why there are no handler tests: `test_order_flow.py` and `test_production_flow.py` in v1 are manual asyncio scripts with a `MockBot`, poking handlers against a live database; `pytest` is not even among the dependencies. That is exactly the price of testing handlers — faking `Bot`, `Message`, `CallbackQuery`, `FSMContext`, and breaking on any edit to a text or a keyboard. The absence of tests in v1 is a consequence of that price, not of laziness.

## What is solved out of v1's problems

| v1 problem | How it is closed |
|---|---|
| #1 persistence of the cart and the jobs | the cart in a table; jobs through the sweep, state in `orders` |
| #2 product–category link by strings | a real FK `products.category_id` |
| #3 no migrations | Alembic from scratch |
| #4 the seed overwrites prices | the seed does not touch existing products |
| #5 duplicated calculation | `domain/` with an import ban checked by a test |
| #6 diverging quantity rules | one rule in `domain/cart_rules.py` |
| #7 a single hardcoded admin | `ADMIN_IDS` + authorisation through the router |
| #8 payments | closed: manual confirmation, no integration |
| #9 the dead Google Sheets feature | not carried over |
| #10 no tests | `pytest`, `domain/` units + service integration tests |
| #11 repository hygiene | a new repository with no secrets, logs or artefacts |
| #12 long polling, one instance | stays, mitigated operationally |

## An action outside the architecture

🔴 **Revoke the Google service-account key.** `mythical-zodiac-496315-t0-7a51ca0567c1.json` is committed in `1c9a259` and remains in the git objects of the old repository.

The new repository does not fix this: the old one is kept, and the key in its history stays valid. Deleting the file and a rule in `.gitignore` **do not revoke** the key — it has to be revoked in the Google Cloud Console.

## Residual risk

The `handlers → services → db` direction still rests on discipline — nothing structurally stops someone, six months from now, from computing straight in a handler again, the way it happened in v1.

Only the `domain/` boundary is guarded mechanically. This is a deliberate narrowing: one checkable boundary around the rules that were being duplicated, instead of an unenforced rule around everything.
