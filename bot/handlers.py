from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

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
        "/stats - показать общую статистику\n"
        "/stats_detailed - статистика по парам\n"
        "/best_pairs - лучшие пары\n"
        "/stats_sides - статистика LONG/SHORT\n"
        "/daily_report - дневной отчёт\n"
        "/weekly_report - недельный отчёт\n"
        "/pnl_stats - PnL в R\n"
        "/export_csv - выгрузить CSV\n"
        "/export_json - выгрузить JSON"
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
async def lastsignals_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
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
async def open_signals_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
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
async def stats_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
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
        f"Winrate: {stats['winrate']}%\n"
        f"Total R: {stats['total_r']}\n"
        f"Avg R: {stats['avg_r']}\n"
        f"Expectancy: {stats['expectancy']}"
    )


@router.message(Command("pnl_stats"))
async def pnl_stats_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = scanner.get_stats()

    await message.answer(
        "💰 PnL статистика в R\n\n"
        f"Закрытых сигналов: {stats['closed']}\n"
        f"Total R: {stats['total_r']}\n"
        f"Avg R: {stats['avg_r']}\n"
        f"Expectancy: {stats['expectancy']}\n"
        f"Winrate: {stats['winrate']}%"
    )


@router.message(Command("stats_detailed"))
async def stats_detailed_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = scanner.get_pair_stats()

    if not rows:
        await message.answer("Детальная статистика пока пуста.")
        return

    lines = ["📈 Статистика по парам:\n"]
    for row in rows[:10]:
        lines.append(
            f"{row['symbol']} | closed={row['closed']} | "
            f"winrate={row['winrate']}% | "
            f"totalR={row['total_r']} | exp={row['expectancy']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("best_pairs"))
async def best_pairs_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = scanner.get_best_pairs(min_closed=1, limit=5)

    if not rows:
        await message.answer("Пока нет лучших пар — ещё мало закрытых сигналов.")
        return

    lines = ["🏆 Лучшие пары:\n"]
    for row in rows:
        lines.append(
            f"{row['symbol']} | winrate={row['winrate']}% | "
            f"closed={row['closed']} | totalR={row['total_r']} | exp={row['expectancy']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("stats_sides"))
async def stats_sides_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    data = scanner.get_side_stats()
    long_stats = data["LONG"]
    short_stats = data["SHORT"]

    await message.answer(
        "📊 Статистика по направлениям\n\n"
        f"LONG:\n"
        f"- total: {long_stats['total']}\n"
        f"- closed: {long_stats['closed']}\n"
        f"- winrate: {long_stats['winrate']}%\n"
        f"- totalR: {long_stats['total_r']}\n"
        f"- avgR: {long_stats['avg_r']}\n"
        f"- expectancy: {long_stats['expectancy']}\n\n"
        f"SHORT:\n"
        f"- total: {short_stats['total']}\n"
        f"- closed: {short_stats['closed']}\n"
        f"- winrate: {short_stats['winrate']}%\n"
        f"- totalR: {short_stats['total_r']}\n"
        f"- avgR: {short_stats['avg_r']}\n"
        f"- expectancy: {short_stats['expectancy']}"
    )


@router.message(Command("daily_report"))
async def daily_report_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    report = scanner.get_daily_report()

    if not report:
        await message.answer("Дневной отчёт пока пуст.")
        return

    lines = ["🗓 Дневной отчёт:\n"]
    for row in report[:7]:
        lines.append(
            f"{row['day']} | closed={row['closed']} | "
            f"winrate={row['winrate']}% | totalR={row['total_r']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("weekly_report"))
async def weekly_report_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    report = scanner.get_weekly_report()

    if not report:
        await message.answer("Недельный отчёт пока пуст.")
        return

    lines = ["📅 Недельный отчёт:\n"]
    for row in report[:7]:
        lines.append(
            f"{row['week']} | closed={row['closed']} | "
            f"winrate={row['winrate']}% | totalR={row['total_r']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("export_csv"))
async def export_csv_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    path = scanner.get_csv_path()
    await message.answer_document(FSInputFile(path), caption="tracked_signals.csv")


@router.message(Command("export_json"))
async def export_json_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    path = scanner.get_json_path()
    await message.answer_document(FSInputFile(path), caption="tracked_signals.json")


@router.message(Command("scan"))
async def scan_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]

    await message.answer("Запускаю ручной анализ рынка. Смотри результат в Telegram и логах.")
    await scanner.scan_market(message.bot, send_to_telegram=True)
    await message.answer("Ручной анализ завершён.")