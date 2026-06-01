import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramConflictError

from bot.handlers import router
from config import Config
from services.db import db
from services.scanner import MarketScanner
from services.telegram_sender import send_text_to_all
from utils.logger import setup_logger

logger = setup_logger()

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


async def send_startup_message(bot: Bot):
    if not Config.SEND_STARTUP_MESSAGE:
        return

    text = (
        "✅ Бот запущен\n\n"
        f"Режим: {Config.STRATEGY_MODE}\n"
        f"Сканирование: каждые {Config.SCAN_INTERVAL_SECONDS} сек\n"
        f"Сопровождение сделок: каждые {Config.OPEN_TRADE_MONITOR_INTERVAL_SECONDS} сек\n"
        f"Пары в анализе: до {Config.MAX_SYMBOLS_TO_SCAN}\n"
        f"Получателей: {len(Config.CHAT_IDS)}\n"
        "Хранение: PostgreSQL"
    )
    await send_text_to_all(bot, Config.CHAT_IDS, text)


async def verify_telegram_polling_owner(bot: Bot):
    logger.info("Boot: проверяю Telegram polling ownership")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.get_updates(timeout=0, allowed_updates=[])
    except TelegramConflictError as error:
        raise RuntimeError(
            "Telegram polling conflict: где-то уже запущен бот с этим BOT_TOKEN. "
            "Останови второй сервис/локальный процесс или перевыпусти токен в BotFather."
        ) from error


async def auto_scan_loop(bot: Bot, scanner: MarketScanner):
    logger.info("Auto scan loop: started")
    while True:
        try:
            logger.info("Auto scan loop: новый цикл сканирования")
            await scanner.scan_market(bot, send_to_telegram=True)
        except Exception as error:
            logger.exception(f"Ошибка в автоцикле: {error}")

        logger.info(f"Жду {Config.SCAN_INTERVAL_SECONDS} секунд до следующего анализа...")
        await asyncio.sleep(Config.SCAN_INTERVAL_SECONDS)


async def open_trade_monitor_loop(bot: Bot, scanner: MarketScanner):
    logger.info("Open trade monitor: started")
    while True:
        try:
            await scanner.monitor_open_signals(bot)
        except Exception as error:
            logger.exception(f"Ошибка в сопровождении открытых сделок: {error}")

        await asyncio.sleep(Config.OPEN_TRADE_MONITOR_INTERVAL_SECONDS)


async def main():
    logger.info("Boot: старт приложения")
    logger.info(
        "Boot: config loaded | "
        f"mode={Config.STRATEGY_MODE} | "
        f"chats={len(Config.CHAT_IDS)} | "
        f"db={'set' if Config.POSTGRES_URI else 'missing'} | "
        f"token={'set' if Config.BOT_TOKEN else 'missing'}"
    )

    if not Config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден. Проверь Variables")
    if not Config.CHAT_IDS:
        raise ValueError("CHAT_IDS не найден. Проверь Variables")

    logger.info("Boot: подключаю PostgreSQL...")
    await asyncio.wait_for(db.connect(), timeout=30)
    logger.info("Boot: PostgreSQL подключён")

    logger.info("Boot: беру production lock")
    lock_acquired = await db.acquire_app_lock()
    if not lock_acquired:
        raise RuntimeError(
            "Production lock уже занят: другая копия этого бота работает с этой PostgreSQL базой."
        )
    logger.info("Boot: production lock получен")

    logger.info("Boot: создаю Telegram bot/dispatcher/scanner")
    bot = Bot(token=Config.BOT_TOKEN)
    await verify_telegram_polling_owner(bot)

    dp = Dispatcher()
    scanner = MarketScanner()

    dp["scanner"] = scanner
    dp.include_router(router)

    logger.info("Boot: отправляю startup message")
    await send_startup_message(bot)
    asyncio.create_task(auto_scan_loop(bot, scanner))
    asyncio.create_task(open_trade_monitor_loop(bot, scanner))

    logger.info("Boot: бот запущен, polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        logger.exception(f"Fatal startup error: {error}")
        raise
