from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import get_main_menu, get_trades_menu

router = Router()


# =====================
# FORMATTERS
# =====================

def fmt_price(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "-"

    if value == 0:
        return "0"

    if abs(value) >= 100:
        return f"{value:.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}"
    if abs(value) >= 0.01:
        return f"{value:.6f}"

    return f"{value:.8f}"


def fmt_r(value) -> str:
    try:
        return f"{float(value):.2f}R"
    except Exception:
        return "-"


# =====================
# STATUS (БЕЗ БАЛАНСА)
# =====================

async def _send_status(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]

    stats = await scanner.get_stats()

    total = int(stats["total"])
    open_ = int(stats["open"])
    closed = int(stats["closed"])

    tp_total = (
        int(stats["tp1_hit"])
        + int(stats["tp2_hit"])
        + int(stats["tp3_hit"])
    )
    stop = int(stats["stop_hit"])

    await message.answer(
        "📊 <b>Состояние системы</b>\n\n"
        "🟢 Бот активен\n\n"
        "📈 <b>Сигналы</b>\n"
        f"Всего: <b>{total}</b>\n"
        f"Открытые: <b>{open_}</b>\n"
        f"Закрытые: <b>{closed}</b>\n\n"
        "🎯 <b>Результаты</b>\n"
        f"TP: <b>{tp_total}</b>\n"
        f"STOP: <b>{stop}</b>\n\n"
        "📊 <b>Качество</b>\n"
        f"Winrate: <b>{stats['winrate']}%</b>\n"
        f"Total R: <b>{stats['total_r']}</b>\n"
        f"Avg R: <b>{stats['avg_r']}</b>\n"
        f"Expectancy: <b>{stats['expectancy']}</b>",
        reply_markup=get_main_menu(),
        parse_mode="HTML",
    )


# =====================
# SIGNAL STATS
# =====================

async def _send_signal_stats(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_stats()

    await message.answer(
        "📈 <b>Статистика сигналов</b>\n\n"
        f"📌 Всего: <b>{stats['total']}</b>\n"
        f"📂 Открытых: <b>{stats['open']}</b>\n"
        f"✅ Закрытых: <b>{stats['closed']}</b>\n\n"
        f"TP1: <b>{stats['tp1_hit']}</b>\n"
        f"TP2: <b>{stats['tp2_hit']}</b>\n"
        f"TP3: <b>{stats['tp3_hit']}</b>\n"
        f"STOP: <b>{stats['stop_hit']}</b>\n\n"
        f"Winrate: <b>{stats['winrate']}%</b>\n"
        f"Total R: <b>{stats['total_r']}</b>\n"
        f"Avg R: <b>{stats['avg_r']}</b>\n"
        f"Expectancy: <b>{stats['expectancy']}</b>",
        reply_markup=get_main_menu(),
        parse_mode="HTML",
    )


# =====================
# LAST SIGNALS
# =====================

async def _send_last_signals(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    signals = await scanner.get_last_logged_signals(limit=7)

    if not signals:
        await message.answer(
            "📌 <b>Последние сигналы</b>\n\nНет данных",
            reply_markup=get_main_menu(),
            parse_mode="HTML",
        )
        return

    text = "📌 <b>Последние сигналы</b>\n\n"

    for s in signals:
        emoji = "🟢" if s["direction"] == "LONG" else "🔴"

        text += (
            f"{emoji} <b>{s['symbol']}</b>\n"
            f"{s['direction']} | Score: <b>{s['score']}</b>\n\n"
        )

    await message.answer(text, reply_markup=get_main_menu(), parse_mode="HTML")


# =====================
# OPEN TRADES
# =====================

async def _send_open_trades(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_open_trades()

    if not trades:
        await message.answer(
            "📂 <b>Открытые сделки</b>\n\nНет активных",
            reply_markup=get_main_menu(),
            parse_mode="HTML",
        )
        return

    text = "📂 <b>Открытые сделки</b>\n\n"

    for t in trades[:10]:
        emoji = "🟢" if t["direction"] == "LONG" else "🔴"

        text += (
            f"{emoji} <b>{t['symbol']}</b> | {t['direction']}\n"
            f"Вход: <b>{fmt_price(t['entry_min'])} - {fmt_price(t['entry_max'])}</b>\n"
            f"Stop: <b>{fmt_price(t['stop_loss'])}</b>\n"
            f"TP1: <b>{fmt_price(t['tp1'])}</b>\n"
            f"TP2: <b>{fmt_price(t['tp2'])}</b>\n"
            f"TP3: <b>{fmt_price(t['tp3'])}</b>\n\n"
        )

    await message.answer(text, reply_markup=get_main_menu(), parse_mode="HTML")


# =====================
# HISTORY
# =====================

async def _send_history(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_history(limit=10)

    if not trades:
        await message.answer(
            "📜 <b>История сделок</b>\n\nПусто",
            reply_markup=get_main_menu(),
            parse_mode="HTML",
        )
        return

    text = "📜 <b>История сделок</b>\n\n"

    for t in trades:
        result = float(t["result_r"] or 0)

        if result > 0:
            emoji = "✅"
        elif result < 0:
            emoji = "❌"
        else:
            emoji = "⚪️"

        text += (
            f"{emoji} <b>{t['symbol']}</b>\n"
            f"{t['direction']} | {fmt_r(result)}\n\n"
        )

    await message.answer(text, reply_markup=get_main_menu(), parse_mode="HTML")


# =====================
# HANDLERS
# =====================

@router.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("👇 Выбери действие:", reply_markup=get_main_menu())


@router.message(lambda m: m.text == "📊 Статус")
async def btn_status(message: Message, dispatcher: Dispatcher):
    await _send_status(message, dispatcher)


@router.message(lambda m: m.text == "📈 Статистика")
async def btn_stats(message: Message, dispatcher: Dispatcher):
    await _send_signal_stats(message, dispatcher)


@router.message(lambda m: m.text == "📌 Сигналы")
async def btn_signals(message: Message, dispatcher: Dispatcher):
    await _send_last_signals(message, dispatcher)


@router.message(lambda m: m.text == "💼 Сделки")
async def btn_trades(message: Message):
    await message.answer("Выбери:", reply_markup=get_trades_menu())


@router.message(lambda m: m.text == "📂 Открытые")
async def btn_open(message: Message, dispatcher: Dispatcher):
    await _send_open_trades(message, dispatcher)


@router.message(lambda m: m.text == "📜 История")
async def btn_history(message: Message, dispatcher: Dispatcher):
    await _send_history(message, dispatcher)


@router.message(lambda m: m.text == "⬅️ Назад")
async def btn_back(message: Message):
    await message.answer("👇 Главное меню:", reply_markup=get_main_menu())