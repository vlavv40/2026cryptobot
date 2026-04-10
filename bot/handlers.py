from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "Привет.\n"
        "Я бот для анализа Binance Futures.\n\n"
        "Команды:\n"
        "/start - запуск\n"
        "/status - статус\n"
        "/scan - ручной запуск анализа"
    )


@router.message(Command("status"))
async def status_handler(message: Message):
    await message.answer("Бот работает. Аналитический движок активен.")


@router.message(Command("scan"))
async def scan_handler(message: Message):
    scanner = message.dispatcher.get("scanner")

    if scanner is None:
        await message.answer("Сканер пока недоступен. Проверь запуск main.py")
        return

    await message.answer("Запускаю ручной анализ рынка. Смотри логи в консоли и сигналы в Telegram.")

    await scanner.scan_market(message.bot, send_to_telegram=True)

    await message.answer("Ручной анализ завершён.")