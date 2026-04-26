from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import get_main_menu, get_trades_menu

router = Router()

# chat_id -> message_id последней UI-панели
last_dashboard_messages: dict[int, int] = {}


# =====================
# UI HELPERS
# =====================

async def delete_previous_dashboard(message: Message):
    chat_id = message.chat.id
    old_message_id = last_dashboard_messages.get(chat_id)

    if not old_message_id:
        return

    try:
        await message.bot.delete_message(chat_id=chat_id, message_id=old_message_id)
    except Exception:
        pass


async def send_dashboard(
    message: Message,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
):
    await delete_previous_dashboard(message)

    msg = await message.answer(
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )

    last_dashboard_messages[message.chat.id] = msg.message_id


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
# STATUS
# =====================

async def _send_status(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_stats()

    tp_total = (
        int(stats["tp1_hit"])
        + int(stats["tp2_hit"])
        + int(stats["tp3_hit"])
    )

    await send_dashboard(
        message,
        "📊 <b>Состояние системы</b>\n\n"
        "🟢 Бот активен\n\n"
        "📈 <b>Сигналы</b>\n"
        f"Всего: <b>{stats['total']}</b>\n"
        f"Открытые: <b>{stats['open']}</b>\n"
        f"Закрытые: <b>{stats['closed']}</b>\n\n"
        "🎯 <b>Результаты</b>\n"
        f"TP: <b>{tp_total}</b>\n"
        f"STOP: <b>{stats['stop_hit']}</b>\n\n"
        "📊 <b>Качество</b>\n"
        f"Winrate: <b>{stats['winrate']}%</b>\n"
        f"Total R: <b>{stats['total_r']}</b>\n"
        f"Avg R: <b>{stats['avg_r']}</b>\n"
        f"Expectancy: <b>{stats['expectancy']}</b>",
        reply_markup=get_main_menu(),
    )


# =====================
# STATS
# =====================

async def _send_signal_stats(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_stats()

    await send_dashboard(
        message,
        "📈 <b>Статистика сигналов</b>\n\n"
        f"📌 Всего: <b>{stats['total']}</b>\n"
        f"📂 Открытых: <b>{stats['open']}</b>\n"
        f"✅ Закрытых: <b>{stats['closed']}</b>\n\n"
        "🎯 <b>Take / Stop</b>\n"
        f"TP1: <b>{stats['tp1_hit']}</b>\n"
        f"TP2: <b>{stats['tp2_hit']}</b>\n"
        f"TP3: <b>{stats['tp3_hit']}</b>\n"
        f"STOP: <b>{stats['stop_hit']}</b>\n\n"
        "📊 <b>R-метрика</b>\n"
        f"Winrate: <b>{stats['winrate']}%</b>\n"
        f"Total R: <b>{stats['total_r']}</b>\n"
        f"Avg R: <b>{stats['avg_r']}</b>\n"
        f"Expectancy: <b>{stats['expectancy']}</b>",
        reply_markup=get_main_menu(),
    )


# =====================
# LAST SIGNALS
# =====================

async def _send_last_signals(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    signals = await scanner.get_last_logged_signals(limit=7)

    if not signals:
        await send_dashboard(
            message,
            "📌 <b>Последние сигналы</b>\n\n"
            "Нет данных.",
            reply_markup=get_main_menu(),
        )
        return

    text = "📌 <b>Последние сигналы</b>\n\n"

    for s in signals:
        direction = s.get("direction", "-")
        emoji = "🟢" if direction == "LONG" else "🔴"

        text += (
            f"{emoji} <b>{s.get('symbol', '-')}</b>\n"
            f"Направление: <b>{direction}</b>\n"
            f"Тип: <b>{s.get('signal_type', 'UNKNOWN')}</b>\n"
            f"Score: <b>{s.get('score', '-')}</b>\n\n"
        )

    await send_dashboard(
        message,
        text,
        reply_markup=get_main_menu(),
    )


# =====================
# OPEN TRADES
# =====================

async def _send_open_trades(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_open_trades()

    if not trades:
        await send_dashboard(
            message,
            "📂 <b>Открытые сделки</b>\n\n"
            "Нет активных сделок.",
            reply_markup=get_main_menu(),
        )
        return

    text = "📂 <b>Открытые сделки</b>\n\n"

    for t in trades[:10]:
        direction = t.get("direction", "-")
        emoji = "🟢" if direction == "LONG" else "🔴"

        text += (
            f"{emoji} <b>{t.get('symbol', '-')}</b> | <b>{direction}</b>\n"
            f"Тип: <b>{t.get('signal_type', '-')}</b>\n"
            f"Вход: <b>{fmt_price(t.get('entry_min'))} - {fmt_price(t.get('entry_max'))}</b>\n"
            f"Stop: <b>{fmt_price(t.get('stop_loss'))}</b>\n"
            f"TP1: <b>{fmt_price(t.get('tp1'))}</b>\n"
            f"TP2: <b>{fmt_price(t.get('tp2'))}</b>\n"
            f"TP3: <b>{fmt_price(t.get('tp3'))}</b>\n\n"
        )

    await send_dashboard(
        message,
        text,
        reply_markup=get_main_menu(),
    )


# =====================
# HISTORY
# =====================

async def _send_history(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    trades = await scanner.get_paper_history(limit=10)

    if not trades:
        await send_dashboard(
            message,
            "📜 <b>История сделок</b>\n\n"
            "История пустая.",
            reply_markup=get_main_menu(),
        )
        return

    text = "📜 <b>История сделок</b>\n\n"

    for t in trades:
        result_r = float(t.get("result_r") or 0)

        if result_r > 0:
            emoji = "✅"
        elif result_r < 0:
            emoji = "❌"
        else:
            emoji = "⚪️"

        text += (
            f"{emoji} <b>{t.get('symbol', '-')}</b>\n"
            f"Направление: <b>{t.get('direction', '-')}</b>\n"
            f"Статус: <b>{t.get('close_reason', '-')}</b>\n"
            f"Результат: <b>{fmt_r(result_r)}</b>\n\n"
        )

    await send_dashboard(
        message,
        text,
        reply_markup=get_main_menu(),
    )


# =====================
# COMMANDS
# =====================

@router.message(Command("start"))
async def start_handler(message: Message):
    await send_dashboard(
        message,
        "👇 <b>Главное меню</b>\n\n"
        "Выбери действие:",
        reply_markup=get_main_menu(),
    )


@router.message(Command("status"))
async def status_handler(message: Message, dispatcher: Dispatcher):
    await _send_status(message, dispatcher)


@router.message(Command("stats"))
async def stats_handler(message: Message, dispatcher: Dispatcher):
    await _send_signal_stats(message, dispatcher)


@router.message(Command("lastsignals"))
async def lastsignals_handler(message: Message, dispatcher: Dispatcher):
    await _send_last_signals(message, dispatcher)


@router.message(Command("open"))
async def open_handler(message: Message, dispatcher: Dispatcher):
    await _send_open_trades(message, dispatcher)


@router.message(Command("history"))
async def history_handler(message: Message, dispatcher: Dispatcher):
    await _send_history(message, dispatcher)


# =====================
# BUTTONS
# =====================

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
    await send_dashboard(
        message,
        "💼 <b>Раздел сделок</b>\n\n"
        "Выбери, что показать:",
        reply_markup=get_trades_menu(),
    )


@router.message(lambda m: m.text == "📂 Открытые")
async def btn_open(message: Message, dispatcher: Dispatcher):
    await _send_open_trades(message, dispatcher)


@router.message(lambda m: m.text == "📜 История")
async def btn_history(message: Message, dispatcher: Dispatcher):
    await _send_history(message, dispatcher)


@router.message(lambda m: m.text == "⬅️ Назад")
async def btn_back(message: Message):
    await send_dashboard(
        message,
        "👇 <b>Главное меню</b>\n\n"
        "Выбери действие:",
        reply_markup=get_main_menu(),
    )