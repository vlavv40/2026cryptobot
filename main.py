import asyncio

from aiogram import Bot, Dispatcher

from bot.handlers import router
from config import Config
from services.scanner import MarketScanner
from services.telegram_sender import send_text_to_all
from utils.logger import setup_logger

logger = setup_logger()


async def send_startup_message(bot: Bot):
    if not Config.SEND_STARTUP_MESSAGE:
        return

    try:
        text = (
            "✅ Бот запущен\n\n"
            f"Режим: {Config.STRATEGY_MODE}\n"
            f"Сканирование: каждые {Config.SCAN_INTERVAL_SECONDS} сек\n"
            f"Пары в анализе: до {Config.MAX_SYMBOLS_TO_SCAN}\n"
            f"Получателей: {len(Config.CHAT_IDS)}"
        )
        await send_text_to_all(bot, Config.CHAT_IDS, text)
    except Exception as error:
        logger.exception(f"Не удалось отправить сообщение о старте: {error}")


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
        raise ValueError("BOT_TOKEN не найден. Проверь Variables")

    if not Config.CHAT_IDS:
        raise ValueError("CHAT_IDS не найден. Проверь Variables")

    bot = Bot(token=Config.BOT_TOKEN)
    dp = Dispatcher()
    scanner = MarketScanner()

    dp["scanner"] = scanner
    dp.include_router(router)

    await send_startup_message(bot)
    asyncio.create_task(auto_scan_loop(bot, scanner))

    logger.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())