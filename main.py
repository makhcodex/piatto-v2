import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMIN_IDS, BOT_TOKEN
from db.engine import dispose_engine
from db.middleware import DatabaseMiddleware
from handlers import build_router
from services.sweep import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Check your .env file.")
    if not ADMIN_IDS:
        raise RuntimeError("ADMIN_IDS is empty — nobody could confirm a payment.")

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # FSM holds only the checkout wizard step. The cart is in Postgres, so losing
    # this on restart costs a re-entry, not an order.
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DatabaseMiddleware())
    dp.include_router(build_router())

    scheduler = create_scheduler(bot)
    scheduler.start()
    logger.info("Sweep scheduler started")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await dispose_engine()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupted")
