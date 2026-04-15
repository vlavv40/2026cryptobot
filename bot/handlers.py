from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import main_menu_keyboard
from config import Config
from services.db import db

router = Router()


async def _send_status(message: Message):
    await message.answer(
        "✅ Бот работает.\n"
        "Хранение данных: PostgreSQL.\n"
        "Управление: кнопки + резервные команды.",
        reply_markup=main_menu_keyboard,
    )


async def _send_mode(message: Message):
    await message.answer(
        "⚙️ Текущие настройки\n\n"
        f"Режим: {Config.STRATEGY_MODE}\n"
        f"Интервал: {Config.SCAN_INTERVAL_SECONDS} сек\n"
        f"Макс сигналов за цикл: {Config.MAX_SIGNALS_PER_SCAN}\n"
        f"Макс пар: {Config.MAX_SYMBOLS_TO_SCAN}\n"
        f"Cooldown: {Config.SIGNAL_COOLDOWN_MINUTES} мин\n"
        f"Strong score/RR: {Config.STRONG_MIN_SCORE} / {Config.STRONG_MIN_RR}\n"
        f"Setup score/RR: {Config.SETUP_MIN_SCORE} / {Config.SETUP_MIN_RR}",
        reply_markup=main_menu_keyboard,
    )


async def _send_heartbeat(message: Message, dispatcher: Dispatcher):
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
        f"Paper PnL: {paper['pnl_usdt']}$",
        reply_markup=main_menu_keyboard,
    )


async def _send_last_signals(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    signals = await scanner.get_last_logged_signals(limit=5)

    if not signals:
        await message.answer("История сигналов пока пуста.", reply_markup=main_menu_keyboard)
        return

    lines = ["📌 Последние сигналы:\n"]
    for item in signals:
        lines.append(
            f"{item['symbol']} | {item['direction']} | "
            f"type={item.get('signal_type', 'UNKNOWN')} | "
            f"score={item['score']}"
        )

    await message.answer("\n".join(lines), reply_markup=main_menu_keyboard)


async def _send_signal_stats(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_stats()

    await message.answer(
        "📈 Статистика сигналов\n\n"
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
        f"Expectancy: {stats['expectancy']}",
        reply_markup=main_menu_keyboard,
    )


async def _send_paper_stats(message: Message, dispatcher: Dispatcher):
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
        f"Winrate: {stats['winrate']}%",
        reply_markup=main_menu_keyboard,
    )


async def _send_open_paper(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_open_trades()

    if not trades:
        await message.answer("Нет открытых paper-сделок.", reply_markup=main_menu_keyboard)
        return

    lines = ["📂 Open Paper Trades\n"]
    for t in trades[:10]:
        notional = round(float(t["entry_price"]) * float(t["size"]), 2)
        state = await scanner.get_paper_stats()
        balance = max(float(state["balance"]), 1.0)
        effective_leverage = round(notional / balance, 2)

        lines.append(
            f"{t['symbol']} | {t['direction']} | {t['signal_type']}\n"
            f"entry={round(float(t['entry_price']), 6)} | SL={round(float(t['stop_loss']), 6)}\n"
            f"risk={round(float(t['risk_amount']), 2)}$ | size={round(float(t['size']), 2)}\n"
            f"notional={notional}$ | eff.leverage={effective_leverage}x\n"
        )

    await message.answer("\n".join(lines), reply_markup=main_menu_keyboard)


async def _send_paper_history(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_history(limit=10)

    if not trades:
        await message.answer("История paper-сделок пока пуста.", reply_markup=main_menu_keyboard)
        return

    lines = ["📜 Last Closed Paper Trades\n"]
    for t in trades:
        lines.append(
            f"{t['symbol']} | {t['direction']} | {t['signal_type']} | "
            f"{t['close_reason']} | {round(float(t['result_usdt']), 2)}$ | R={round(float(t['result_r']), 2)}"
        )

    await message.answer("\n".join(lines), reply_markup=main_menu_keyboard)


async def _run_manual_scan(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    await message.answer("🔄 Запускаю ручной анализ...", reply_markup=main_menu_keyboard)
    await scanner.scan_market(message.bot, send_to_telegram=True)
    await message.answer("✅ Ручной анализ завершён.", reply_markup=main_menu_keyboard)


async def _reset_paper(message: Message):
    assert db.pool is not None
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM paper_trades;")
        await conn.execute("UPDATE paper_state SET start_balance=10000, balance=10000, risk_per_trade=0.01 WHERE id=1;")
    await message.answer("🧹 Paper trading сброшен. Новый тест начат с 10 000$.", reply_markup=main_menu_keyboard)


@router.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "Привет.\n"
        "Теперь бот работает через кнопки.\n"
        "Выбери действие ниже.",
        reply_markup=main_menu_keyboard,
    )


@router.message(Command("status"))
async def status_handler(message: Message):
    await _send_status(message)


@router.message(Command("heartbeat"))
async def heartbeat_handler(message: Message, dispatcher: Dispatcher):
    await _send_heartbeat(message, dispatcher)


@router.message(Command("mode"))
async def mode_handler(message: Message):
    await _send_mode(message)


@router.message(Command("lastsignals"))
async def lastsignals_handler(message: Message, dispatcher: Dispatcher):
    await _send_last_signals(message, dispatcher)


@router.message(Command("stats"))
async def stats_handler(message: Message, dispatcher: Dispatcher):
    await _send_signal_stats(message, dispatcher)


@router.message(Command("paper_stats"))
async def paper_stats_handler(message: Message, dispatcher: Dispatcher):
    await _send_paper_stats(message, dispatcher)


@router.message(Command("paper_open"))
async def paper_open_handler(message: Message, dispatcher: Dispatcher):
    await _send_open_paper(message, dispatcher)


@router.message(Command("paper_history"))
async def paper_history_handler(message: Message, dispatcher: Dispatcher):
    await _send_paper_history(message, dispatcher)


@router.message(Command("scan"))
async def scan_handler(message: Message, dispatcher: Dispatcher):
    await _run_manual_scan(message, dispatcher)


@router.message(lambda message: message.text == "📊 Статус")
async def button_status(message: Message):
    await _send_status(message)


@router.message(lambda message: message.text == "💓 Heartbeat")
async def button_heartbeat(message: Message, dispatcher: Dispatcher):
    await _send_heartbeat(message, dispatcher)


@router.message(lambda message: message.text == "⚙️ Mode")
async def button_mode(message: Message):
    await _send_mode(message)


@router.message(lambda message: message.text == "📌 Last signals")
async def button_last_signals(message: Message, dispatcher: Dispatcher):
    await _send_last_signals(message, dispatcher)


@router.message(lambda message: message.text == "📈 Signal stats")
async def button_signal_stats(message: Message, dispatcher: Dispatcher):
    await _send_signal_stats(message, dispatcher)


@router.message(lambda message: message.text == "🧪 Paper stats")
async def button_paper_stats(message: Message, dispatcher: Dispatcher):
    await _send_paper_stats(message, dispatcher)


@router.message(lambda message: message.text == "📂 Open paper")
async def button_open_paper(message: Message, dispatcher: Dispatcher):
    await _send_open_paper(message, dispatcher)


@router.message(lambda message: message.text == "📜 Paper history")
async def button_paper_history(message: Message, dispatcher: Dispatcher):
    await _send_paper_history(message, dispatcher)


@router.message(lambda message: message.text == "🔄 Scan now")
async def button_scan_now(message: Message, dispatcher: Dispatcher):
    await _run_manual_scan(message, dispatcher)


@router.message(lambda message: message.text == "🧹 Reset paper")
async def button_reset_paper(message: Message):
    await _reset_paper(message)