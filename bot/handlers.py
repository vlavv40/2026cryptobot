from aiogram import Dispatcher, Router
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
        "/status\n"
        "/heartbeat\n"
        "/mode\n"
        "/lastsignals\n"
        "/open_signals\n"
        "/stats\n"
        "/stats_detailed\n"
        "/best_pairs\n"
        "/stats_sides\n"
        "/daily_report\n"
        "/weekly_report\n"
        "/pnl_stats\n"
        "/paper_stats\n"
        "/paper_open\n"
        "/paper_history\n"
        "/scan"
    )


@router.message(Command("status"))
async def status_handler(message: Message):
    await message.answer("Бот работает. Данные сохраняются в PostgreSQL.")


@router.message(Command("heartbeat"))
async def heartbeat_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    hb = await scanner.get_heartbeat()
    cycle = hb["last_cycle"]
    paper = hb["paper_stats"]

    top_symbols = ", ".join(cycle.get("top_signal_symbols", [])) if cycle.get("top_signal_symbols") else "нет"

    await message.answer(
        "💓 Heartbeat\n\n"
        f"Режим: {hb['mode']}\n"
        f"Интервал: {hb['scan_interval']} сек\n"
        f"Открытых сигналов: {hb['open_signals']}\n"
        f"Старт последнего цикла: {cycle.get('started_at')}\n"
        f"Финиш последнего цикла: {cycle.get('finished_at')}\n"
        f"News block: {cycle.get('news_block')}\n"
        f"Причина news guard: {cycle.get('news_reason')}\n"
        f"Sentiment: {cycle.get('sentiment')}\n"
        f"Проверено пар: {cycle.get('symbols_checked')}\n"
        f"Сильных сигналов: {cycle.get('signals_found')}\n"
        f"Top symbols: {top_symbols}\n\n"
        f"Paper balance: {paper['balance']}$\n"
        f"Paper PnL: {paper['pnl_usdt']}$"
    )


@router.message(Command("mode"))
async def mode_handler(message: Message):
    await message.answer(
        "⚙️ Текущие настройки\n\n"
        f"Режим: {Config.STRATEGY_MODE}\n"
        f"Интервал: {Config.SCAN_INTERVAL_SECONDS} сек\n"
        f"Макс сигналов за цикл: {Config.MAX_SIGNALS_PER_SCAN}\n"
        f"Макс пар: {Config.MAX_SYMBOLS_TO_SCAN}\n"
        f"Cooldown: {Config.SIGNAL_COOLDOWN_MINUTES} мин\n"
        f"Strong score/RR: {Config.STRONG_MIN_SCORE} / {Config.STRONG_MIN_RR}\n"
        f"Setup score/RR: {Config.SETUP_MIN_SCORE} / {Config.SETUP_MIN_RR}"
    )


@router.message(Command("lastsignals"))
async def lastsignals_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    signals = await scanner.get_last_logged_signals(limit=5)

    if not signals:
        await message.answer("История сигналов пока пуста.")
        return

    lines = ["📌 Последние сигналы:\n"]
    for item in signals:
        lines.append(
            f"{item['symbol']} | {item['direction']} | "
            f"type={item.get('signal_type', 'UNKNOWN')} | "
            f"score={item['score']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("open_signals"))
async def open_signals_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    signals = await scanner.get_open_signals()

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
    stats = await scanner.get_stats()

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
    stats = await scanner.get_stats()

    await message.answer(
        "💰 PnL в R\n\n"
        f"Закрытых сигналов: {stats['closed']}\n"
        f"Total R: {stats['total_r']}\n"
        f"Avg R: {stats['avg_r']}\n"
        f"Expectancy: {stats['expectancy']}\n"
        f"Winrate: {stats['winrate']}%"
    )


@router.message(Command("stats_detailed"))
async def stats_detailed_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = await scanner.get_pair_stats()

    if not rows:
        await message.answer("Детальная статистика пока пуста.")
        return

    lines = ["📈 Статистика по парам:\n"]
    for row in rows[:10]:
        lines.append(
            f"{row['symbol']} | closed={row['closed']} | "
            f"winrate={row['winrate']}% | totalR={row['total_r']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("best_pairs"))
async def best_pairs_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = await scanner.get_best_pairs(min_closed=1, limit=5)

    if not rows:
        await message.answer("Пока нет лучших пар.")
        return

    lines = ["🏆 Лучшие пары:\n"]
    for row in rows:
        lines.append(
            f"{row['symbol']} | winrate={row['winrate']}% | "
            f"closed={row['closed']} | totalR={row['total_r']}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("stats_sides"))
async def stats_sides_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    data = await scanner.get_side_stats()
    long_stats = data["LONG"]
    short_stats = data["SHORT"]

    await message.answer(
        "📊 Статистика по направлениям\n\n"
        f"LONG:\n"
        f"- total: {long_stats['total']}\n"
        f"- closed: {long_stats['closed']}\n"
        f"- winrate: {long_stats['winrate']}%\n"
        f"- totalR: {long_stats['total_r']}\n\n"
        f"SHORT:\n"
        f"- total: {short_stats['total']}\n"
        f"- closed: {short_stats['closed']}\n"
        f"- winrate: {short_stats['winrate']}%\n"
        f"- totalR: {short_stats['total_r']}"
    )


@router.message(Command("daily_report"))
async def daily_report_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    report = await scanner.get_daily_report()

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
    report = await scanner.get_weekly_report()

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


@router.message(Command("paper_stats"))
async def paper_stats_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_paper_stats()

    await message.answer(
        "🧪 Paper Trading Stats\n\n"
        f"Start balance: {stats['start_balance']}$\n"
        f"Current balance: {stats['balance']}$\n"
        f"PnL: {stats['pnl_usdt']}$\n"
        f"Total R: {stats['total_r']}\n"
        f"Total trades: {stats['total_trades']}\n"
        f"Open trades: {stats['open_trades']}\n"
        f"Closed trades: {stats['closed_trades']}\n"
        f"Wins: {stats['wins']}\n"
        f"Losses: {stats['losses']}\n"
        f"Winrate: {stats['winrate']}%"
    )


@router.message(Command("paper_open"))
async def paper_open_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_open_trades()

    if not trades:
        await message.answer("Нет открытых paper-сделок.")
        return

    lines = ["📂 Open Paper Trades\n"]
    for t in trades[:10]:
        lines.append(
            f"{t['symbol']} | {t['direction']} | {t['signal_type']} | "
            f"entry={round(t['entry_price'], 6)} | risk={round(t['risk_amount'], 2)}$"
        )

    await message.answer("\n".join(lines))


@router.message(Command("paper_history"))
async def paper_history_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_history(limit=10)

    if not trades:
        await message.answer("История paper-сделок пока пуста.")
        return

    lines = ["📜 Last Closed Paper Trades\n"]
    for t in trades:
        lines.append(
            f"{t['symbol']} | {t['direction']} | {t['signal_type']} | "
            f"{t['close_reason']} | {round(t['result_usdt'], 2)}$ | R={round(t['result_r'], 2)}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("scan"))
async def scan_handler(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    await message.answer("Запускаю ручной анализ рынка.")
    await scanner.scan_market(message.bot, send_to_telegram=True)
    await message.answer("Ручной анализ завершён.")