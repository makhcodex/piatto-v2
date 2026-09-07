# Deploying Piatto to Railway

Runbook for a single Railway service running the bot as a long-polling `worker`.
Nothing here is a secret: fill the values in the Railway dashboard, never in the repo.

## Service shape

- **One service, one instance.** `railway.json` pins `numReplicas: 1`.
- **No HTTP port, no healthcheck path, no `web` process.** The bot dials out to
  Telegram over long polling; it never listens. A healthcheck would fail forever
  on a service that has nothing to check.
- **Builder: Nixpacks.** `runtime.txt` pins the interpreter to `python-3.11`;
  `requirements.txt` is the full dependency list, installed by Nixpacks.

### Why one instance matters

Long polling with `getUpdates` is exclusive per bot token. A second instance on the
same `BOT_TOKEN` makes Telegram return `409 Conflict: terminated by other
getUpdates request` and the two replicas fight over every update — some messages
land on one, some on the other, some are lost. This was a v1 bug. Do not scale this
service horizontally, and do not run a local `python main.py` against the same token
while the deployment is live.

## Environment variables

Names come from `config.py`. Set them on the service in the Railway dashboard.

| Variable | Required | Secret | Default | Notes |
| --- | --- | --- | --- | --- |
| `BOT_TOKEN` | yes | yes | — | Telegram bot token from @BotFather. Empty aborts startup. |
| `DATABASE_URL` | yes | yes | — | Set it as a reference to the Postgres plugin: `${{Postgres.DATABASE_URL}}`. See *DATABASE_URL scheme* below. |
| `ADMIN_IDS` | yes | no | — | Comma-separated Telegram user ids, e.g. `12345,67890`. Empty aborts startup: with no admin nobody could confirm a payment. |
| `PAYMENT_CARD_NUMBER` | yes | yes | — | Card shown to the customer for the manual transfer. Empty aborts startup: nobody could pay, and the sweep would auto-cancel every order after `CANCEL_MINUTES`. |
| `LOGO_URL` | no | no | `""` | Optional branding image. |
| `WARNING_MINUTES` | no | no | `10` | Minutes before the payment reminder. |
| `CANCEL_MINUTES` | no | no | `20` | Minutes before an unpaid order is auto-cancelled. |
| `SWEEP_INTERVAL_SECONDS` | no | no | `60` | Sweep tick. Reminder and cancel timing are accurate to +/- this value. |
| `ORDER_RATE_LIMIT` | no | no | `5` | Orders per user per hour. |

`TEST_DATABASE_URL` is read only by `tests/services/conftest.py`. Never set it on the
production service — the suite drops and recreates the schema of whatever it points at.

## Pre-deploy Command

Set this in the Railway dashboard under **Settings → Deploy → Pre-deploy Command**:

```
alembic upgrade head
```

It is deliberately *not* in `railway.json` and *not* in `main.py`:

- Railway runs the Pre-deploy Command in the application image, once per deploy,
  and only starts the new instance if it exits `0`. A failed migration therefore
  blocks the rollout instead of producing a running bot against a stale schema.
- Putting it in `startCommand` would re-run migrations on every crash-restart, and
  `restartPolicyType: ON_FAILURE` means restarts are expected.
- Migrations are a deploy-time step, not a runtime one — the same split the local
  runbook uses (`alembic upgrade head`, then `python main.py`).

The pre-deploy step runs inside the app image, so everything it needs — `alembic`,
`SQLAlchemy`, `asyncpg`, `python-dotenv`, and the `config` / `db.models` imports in
`migrations/env.py` — must be in `requirements.txt`. It is; do not move any of them
to a dev-only list.

## Start command

`railway.json` → `deploy.startCommand` is the single source of truth:

```
python main.py
```

The `Procfile` that used to declare `worker: python main.py` has been removed. It
named the same command, but two files declaring the start command is one too many —
`railway.json` wins, and the loser drifts silently. Do not reintroduce it: change
the command here.

## DATABASE_URL scheme

Railway's Postgres plugin publishes `DATABASE_URL` with a bare scheme —
`postgres://…` or `postgresql://…`, no driver. Both `db/engine.py` and
`migrations/env.py` call `create_async_engine`, which needs an explicit async
driver, and would otherwise reach for the default sync DBAPI and fail with
`The asyncio extension requires an async driver`.

`config.py` normalises this: a bare `postgres://` or `postgresql://` scheme is
rewritten to `postgresql+asyncpg://`. A URL that already names a driver
(`+asyncpg`, `+psycopg`) is passed through untouched, so a hand-set value still
wins. Both the bot and the migrations import `DATABASE_URL` from `config.py`, so
they can never disagree about the driver — there is no separate sync migration
path and no `psycopg2` in the dependency list.

One caveat the normalisation does not cover: asyncpg does not understand libpq's
`?sslmode=…` query parameter, and SQLAlchemy's asyncpg dialect does not translate
it. Railway's internal `DATABASE_URL` carries no such parameter. If you ever point
the service at an external database whose URL has one, strip it and configure TLS
through asyncpg's own `ssl` argument instead.

## Deploy checklist

1. Provision Postgres in the Railway project.
2. Create the service from the repo. Confirm it is a `worker`: no domain generated,
   no port exposed.
3. Set every required variable from the table above; reference the plugin for
   `DATABASE_URL`.
4. Set the Pre-deploy Command to `alembic upgrade head`.
5. Deploy. Watch the logs for `Sweep scheduler started`, then message the bot.
6. Seed the menu once, if this is a fresh database: `python -m scripts.seed`, run
   from a Railway shell or locally against the same `DATABASE_URL`. It is not part
   of startup and is safe to re-run — it never overwrites a price edited in the bot.
