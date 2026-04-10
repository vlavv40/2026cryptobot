from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Config

router = Router()


@router.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "Привет.\n"
        "Я бот для анализа Binance Futures.\n\n"
        "Команды:\n"
        "/start - запуск\n"
        "/status - статус\n"
        "/scan - ручной запуск анализа\n"
        "/chatid - показать ID текущего чата\n"
        "/mode - показать текущие настройки\n"
        "/lastsignals - показать последние сигналы\n"
        "/open_signals - показать открытые сигналы\n"
        "/stats - показать статистику\n"
        "/stats_detailed - статистика по парам\n"
        "/best_pairs - лучшие пары"
    )


@router.message(Command("status"))
async def status_handler(message: Message):
    await message.answer("Бот работает. Аналитический движок активен.")


@router.message(Command("chatid"))
async def chatid_handler(message: Message):
    await message.answer(
        f"ID этого чата:\n{message.chat.id}\n\n"
        f"Тип чата: {message.chat.type}"
    )


@router.message(Command("mode"))
async def mode_handler(message: Message):
    await message.answer(
        "⚙️ Текущие настройки бота\n\n"
        f"Режим: {Config.STRATEGY_MODE}\n"
        f"Интервал сканирования: {Config.SCAN_INTERVAL_SECONDS} сек\n"
        f"Максимум сигналов за цикл: {Config.MAX_SIGNALS_PER_SCAN}\n"
        f"Только priority-пары: {Config.USE_PRIORITY_SYMBOLS_ONLY}\n"
        f"Максимум пар: {Config.MAX_SYMBOLS_TO_SCAN}\n"
        f"Cooldown: {Config.SIGNAL_COOLDOWN_MINUTES} мин\n"
        f"Min score: {Config.MIN_SCORE}\n"
        f"Min RR: {Config.MIN_RR}"
    )


@router.message(Command("lastsignals"))
async def lastsignals_handler(message: Message):
    scanner = message.dispatcher.get("scanner")

    if scanner is None:
        await message.answer("Сканер пока недоступен.")
        return

    signals = scanner.get_last_logged_signals(limit=5)

    if not signals:
        await message.answer("История сигналов пока пуста.")
        return

    lines = ["📌 Последние сигналы:\n"]
    for item in signals:
        lines.append(
            f"{item['symbol']} | {item['direction']} | "
            f"score={item['score']} | "
            f"entry={item['entry_min']} - {item['entry_max']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("open_signals"))
async def open_signals_handler(message: Message):
    scanner = message.dispatcher.get("scanner")

    if scanner is None:
        await message.answer("Сканер пока недоступен.")
        return

    signals = scanner.get_open_signals()

    if not signals:
        await message.answer("Сейчас нет открытых сигналов.")
        return

    lines = ["📂 Открытые сигналы:\n"]
    for item in signals[:10]:
        lines.append(
            f"{item['symbol']} | {item['direction']} | "
            f"entry={item['entry_min']} - {item['entry_max']} | "
            f"SL={item['stop_loss']} | TP1={item['tp1']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("stats"))
async def stats_handler(message: Message):
    scanner = message.dispatcher.get("scanner")

    if scanner is None:
        await message.answer("Сканер пока недоступен.")
        return

    stats = scanner.get_stats()

    await message.answer(
        "📊 Статистика сигналов\n\n"
        f"Всего: {stats['total']}\n"
        f"Открытых: {stats['open']}\n"
        f"Закрытых: {stats['closed']}\n"
        f"TP1: {stats['tp1_hit']}\n"
        f"TP2: {stats['tp2_hit']}\n"
        f"TP3: {stats['tp3_hit']}\n"
        f"STOP: {stats['stop_hit']}\n"
        f"Winrate: {stats['winrate']}%"
    )


@router.message(Command("stats_detailed"))
async def stats_detailed_handler(message: Message):
    scanner = message.dispatcher.get("scanner")

    if scanner is None:
        await message.answer("Сканер пока недоступен.")
        return

    rows = scanner.get_pair_stats()

    if not rows:
        await message.answer("Детальная статистика пока пуста.")
        return

    lines = ["📈 Статистика по парам:\n"]
    for row in rows[:10]:
        lines.append(
            f"{row['symbol']} | total={row['total']} | "
            f"closed={row['closed']} | stop={row['stop_hit']} | "
            f"winrate={row['winrate']}%"
        )

    await message.answer("\n".join(lines))


@router.message(Command("best_pairs"))
async def best_pairs_handler(message: Message):
    scanner = message.dispatcher.get("scanner")

    if scanner is None:
        await message.answer("Сканер пока недоступен.")
        return

    rows = scanner.get_best_pairs(min_closed=1, limit=5)

    if not rows:
        await message.answer("Пока нет лучших пар — ещё мало закрытых сигналов.")
        return

    lines = ["🏆 Лучшие пары:\n"]
    for row in rows:
        lines.append(
            f"{row['symbol']} | winrate={row['winrate']}% | "
            f"closed={row['closed']} | stop={row['stop_hit']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("scan"))
async def scan_handler(message: Message):
    scanner = message.dispatcher.get("scanner")

    if scanner is None:
        await message.answer("Сканер пока недоступен. Проверь запуск main.py")
        return

    await message.answer("Запускаю ручной анализ рынка. Смотри результат в Telegram и логах.")

    await scanner.scan_market(message.bot, send_to_telegram=True)

    await message.answer("Ручной анализ завершён.")