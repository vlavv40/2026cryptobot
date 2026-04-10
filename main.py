import asyncio

from aiogram import Bot, Dispatcher

from bot.handlers import router
from config import Config
from services.scanner import MarketScanner
from utils.logger import setup_logger

logger = setup_logger()


async def auto_scan_loop(bot: Bot, scanner: MarketScanner):
    while True:
        try:
            await scanner.scan_market(bot, send_to_telegram=True)
        except Exception as error:
            logger.exception(f"Ошибка в автоцикле: {error}")

        logger.info(f"Жду {Config.SCAN_INTERVAL_SECONDS} секунд до следующего анализа...")
        await asyncio.sleep(Config.SCAN_INTERVAL_SECONDS)


async def main():
    if not Config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден. Проверь файл .env")

    if not Config.CHAT_ID:
        raise ValueError("CHAT_ID не найден. Проверь файл .env")

    bot = Bot(token=Config.BOT_TOKEN)
    dp = Dispatcher()
    scanner = MarketScanner()

    dp["scanner"] = scanner

    dp.include_router(router)

    asyncio.create_task(auto_scan_loop(bot, scanner))

    logger.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())