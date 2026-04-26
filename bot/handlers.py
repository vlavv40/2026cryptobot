from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import get_main_menu, get_trades_menu
from services.db import db

router = Router()


# =====================
# БАЗОВЫЕ
# =====================

async def _send_status(message: Message):
    await message.answer(
        "✅ Бот работает",
        reply_markup=get_main_menu(),
    )


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
        reply_markup=get_main_menu(),
    )


async def _send_last_signals(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    signals = await scanner.get_last_logged_signals(limit=5)

    if not signals:
        await message.answer("Нет сигналов.", reply_markup=get_main_menu())
        return

    text = "📌 Последние сигналы\n\n"

    for s in signals:
        text += f"{s['symbol']} | {s['direction']} | score={s['score']}\n"

    await message.answer(text, reply_markup=get_main_menu())


# =====================
# СДЕЛКИ
# =====================

async def _send_open_trades(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_open_trades()

    if not trades:
        await message.answer("Нет открытых сделок.", reply_markup=get_main_menu())
        return

    text = "📂 Открытые сделки\n\n"

    for t in trades[:10]:
        text += f"{t['symbol']} | {t['direction']}\n"

    await message.answer(text, reply_markup=get_main_menu())


async def _send_history(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_history(limit=10)

    if not trades:
        await message.answer("История пустая.", reply_markup=get_main_menu())
        return

    text = "📜 История сделок\n\n"

    for t in trades:
        text += f"{t['symbol']} | {t['result_usdt']}$ | R={t['result_r']}\n"

    await message.answer(text, reply_markup=get_main_menu())


# =====================
# СБРОС
# =====================

async def _reset(message: Message):
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM paper_trades;")
        await conn.execute(
            "UPDATE paper_state SET start_balance=1000, balance=1000, risk_per_trade=0 WHERE id=1;"
        )

    await message.answer("🧹 Статистика сброшена", reply_markup=get_main_menu())


# =====================
# HANDLERS
# =====================

@router.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "Выбери действие:",
        reply_markup=get_main_menu(),
    )


@router.message(lambda m: m.text == "📊 Статус")
async def btn_status(message: Message):
    await _send_status(message)


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
    await message.answer("Главное меню", reply_markup=get_main_menu())


@router.message(lambda m: m.text == "🧹 Сброс")
async def btn_reset(message: Message):
    await _reset(message)