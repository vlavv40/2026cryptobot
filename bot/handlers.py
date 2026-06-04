import asyncio
import os
from datetime import datetime

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types import FSInputFile

from bot.keyboards import (
    get_admin_menu,
    get_export_menu,
    get_main_menu,
    get_reset_db_confirm_menu,
    get_stats_menu,
    get_trades_menu,
)
from config import Config
from services.stats_window import stats_period_label

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


def fmt_money(value) -> str:
    try:
        return f"{float(value):.2f}$"
    except Exception:
        return "-"


def fmt_signed_money(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "-"

    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}$"


def fmt_pct(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "-"

    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def fmt_minutes(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "-"

    if value < 60:
        return f"{value:.0f} мин"

    hours = value / 60
    if hours < 48:
        return f"{hours:.1f} ч"

    return f"{hours / 24:.1f} д"


def trade_entry_price(trade: dict) -> float:
    entry_price = as_float(trade.get("entry_price"))
    if entry_price > 0:
        return entry_price

    entry_min = as_float(trade.get("entry_min"))
    entry_max = as_float(trade.get("entry_max"))
    return (entry_min + entry_max) / 2.0


def trade_move_pct(direction: str, entry_price: float, price: float) -> float:
    if entry_price <= 0:
        return 0.0

    if direction == "LONG":
        return (price - entry_price) / entry_price

    return (entry_price - price) / entry_price


def trade_stage_label(stage: str) -> str:
    if stage == "TP2_HIT":
        return "TP2 взят, остаток идет к TP3"
    if stage == "TP1_HIT":
        return "TP1 взят, сделка защищена"
    return "в работе, TP1 ещё не взят"


def trade_remaining_share(stage: str) -> float:
    if stage == "TP2_HIT":
        return 0.10
    if stage == "TP1_HIT":
        return 0.30
    return 1.0


def trade_realized_partial_pnl(trade: dict, position_usdt: float, entry_price: float) -> float:
    direction = trade.get("direction", "-")
    stage = trade.get("protection_stage") or "INITIAL"
    realized = 0.0

    if stage in {"TP1_HIT", "TP2_HIT"}:
        realized += position_usdt * 0.70 * trade_move_pct(
            direction,
            entry_price,
            as_float(trade.get("tp1")),
        )

    if stage == "TP2_HIT":
        realized += position_usdt * 0.20 * trade_move_pct(
            direction,
            entry_price,
            as_float(trade.get("tp2")),
        )

    return realized


def trade_live_numbers(trade: dict, current_price: float, position_usdt: float) -> dict:
    direction = trade.get("direction", "-")
    stage = trade.get("protection_stage") or "INITIAL"
    entry_price = trade_entry_price(trade)
    active_stop = as_float(trade.get("active_stop_loss") or trade.get("stop_loss"))
    remaining_share = trade_remaining_share(stage)
    realized_pnl = trade_realized_partial_pnl(trade, position_usdt, entry_price)
    current_move_pct = trade_move_pct(direction, entry_price, current_price)
    stop_move_pct = trade_move_pct(direction, entry_price, active_stop)

    live_pnl = realized_pnl + position_usdt * remaining_share * current_move_pct
    stop_pnl = realized_pnl + position_usdt * remaining_share * stop_move_pct

    if stage == "TP2_HIT":
        next_name = "TP3"
        next_price = as_float(trade.get("tp3"))
    elif stage == "TP1_HIT":
        next_name = "TP2"
        next_price = as_float(trade.get("tp2"))
    else:
        next_name = "TP1"
        next_price = as_float(trade.get("tp1"))

    if direction == "LONG":
        stop_distance_pct = ((current_price - active_stop) / current_price) * 100 if current_price else 0.0
        next_distance_pct = ((next_price - current_price) / current_price) * 100 if current_price else 0.0
    else:
        stop_distance_pct = ((active_stop - current_price) / current_price) * 100 if current_price else 0.0
        next_distance_pct = ((current_price - next_price) / current_price) * 100 if current_price else 0.0

    return {
        "entry_price": entry_price,
        "active_stop": active_stop,
        "live_pnl": round(live_pnl, 2),
        "stop_pnl": round(stop_pnl, 2),
        "stop_distance_pct": stop_distance_pct,
        "next_name": next_name,
        "next_price": next_price,
        "next_distance_pct": next_distance_pct,
    }


def is_admin(message: Message) -> bool:
    return str(message.chat.id) in Config.CHAT_IDS


async def guard_admin(message: Message) -> bool:
    if is_admin(message):
        return True

    await message.answer("Доступно только администратору.")
    return False


# =====================
# STATUS
# =====================

async def _send_status(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_stats()
    paper_stats = await scanner.get_paper_stats()
    heartbeat = await scanner.get_heartbeat()
    last_cycle = heartbeat.get("last_cycle", {})

    tp_total = (
        int(stats["tp1_hit"])
        + int(stats["tp2_hit"])
        + int(stats["tp3_hit"])
    )

    await send_dashboard(
        message,
        "📊 <b>Состояние системы</b>\n\n"
        "🟢 Бот активен\n\n"
        "⚙️ <b>Цикл</b>\n"
        f"Режим: <b>{heartbeat.get('mode')}</b>\n"
        f"Интервал: <b>{heartbeat.get('scan_interval')} сек</b>\n"
        f"Последний запуск: <b>{last_cycle.get('started_at') or '-'}</b>\n"
        f"Проверено пар: <b>{last_cycle.get('symbols_checked', 0)}</b>\n\n"
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
        f"Expectancy: <b>{stats['expectancy']}</b>\n\n"
        "💵 <b>Paper</b>\n"
        f"PnL: <b>{fmt_money(paper_stats.get('pnl_usdt'))}</b>\n"
        f"Risk open: <b>{fmt_money(paper_stats.get('open_risk_usdt'))}</b>\n"
        f"Volume open: <b>{fmt_money(paper_stats.get('open_volume_usdt'))}</b>\n"
        f"Protected: <b>{paper_stats.get('protected_trades', 0)}</b>",
        reply_markup=get_main_menu(),
    )


# =====================
# STATS
# =====================

async def _send_signal_stats(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_stats()
    paper_stats = await scanner.get_paper_stats()
    period = stats_period_label()
    clean_stop = int(stats.get("clean_stop_hit") or 0)
    protected_stop = int(stats.get("protected_stop_hit") or 0)
    wins = int(stats.get("wins") or 0)
    losses = int(stats.get("losses") or 0)
    closed = int(stats.get("closed") or 0)
    open_count = int(stats.get("open") or 0)
    protected_now = int(paper_stats.get("protected_trades", 0) or 0)
    trade_margin_usdt = float(paper_stats.get("trade_margin_usdt") or 0.0)
    trade_leverage = int(paper_stats.get("trade_leverage") or 0)
    trade_position_usdt = float(paper_stats.get("trade_position_usdt") or 0.0)
    pnl_usdt = float(paper_stats.get("pnl_usdt") or 0.0)
    open_risk_usdt = float(paper_stats.get("open_risk_usdt") or 0.0)
    worst_case_pnl = pnl_usdt - open_risk_usdt

    if float(stats.get("expectancy") or 0.0) > 0:
        conclusion = "бот сейчас торгует в плюс."
    elif closed < 10:
        conclusion = "сделок ещё мало, вывод рано делать."
    else:
        conclusion = "математика слабая, нужно снижать риск или править фильтры."

    await send_dashboard(
        message,
        f"📈 <b>Статистика {period}</b>\n\n"
        f"🧠 <b>Главное:</b> {conclusion}\n\n"
        "💰 <b>Деньги</b>\n"
        f"PnL закрытых: <b>{fmt_money(pnl_usdt)}</b>\n"
        f"Результат: <b>{stats['total_r']}R</b>\n"
        f"Средняя сделка: <b>{stats['expectancy']}R</b>\n\n"
        "📌 <b>Сделки</b>\n"
        f"Закрыто: <b>{closed}</b> | плюс: <b>{wins}</b> | минус: <b>{losses}</b>\n"
        f"Полный стоп: <b>{clean_stop}</b>\n"
        f"Стоп после прибыли: <b>{protected_stop}</b>\n\n"
        "🟡 <b>Сейчас</b>\n"
        f"Открыто: <b>{open_count}</b> | защищено: <b>{protected_now}</b>\n"
        f"Маржа на сделку: <b>{fmt_money(trade_margin_usdt)}</b> | плечо: <b>x{trade_leverage}</b>\n"
        f"Позиция на сделку: <b>{fmt_money(trade_position_usdt)}</b>\n"
        f"Риск в рынке: <b>{fmt_money(open_risk_usdt)}</b>\n"
        f"Если все стопы сейчас: <b>{fmt_money(worst_case_pnl)}</b>\n\n"
        "Маржа = сколько занято на вход. "
        "Риск = сколько можно потерять до стопа.",
        reply_markup=get_stats_menu(),
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
            reply_markup=get_trades_menu(),
        )
        return

    async def enrich_trade(trade: dict) -> dict:
        trade = dict(trade)
        try:
            trade["current_price"] = await scanner.execution.get_mark_price(trade["symbol"])
        except Exception as error:
            trade["current_price_error"] = str(error)
        return trade

    live_trades = await asyncio.gather(*(enrich_trade(t) for t in trades[:10]))
    paper_stats = await scanner.get_paper_stats()
    closed_pnl = as_float(paper_stats.get("pnl_usdt"))
    position_usdt = as_float(paper_stats.get("trade_position_usdt")) or (
        Config.AUTO_TRADE_USDT * Config.AUTO_TRADE_LEVERAGE
    )

    total_live_pnl = 0.0
    total_stop_pnl = 0.0
    live_rows: list[tuple[dict, dict | None]] = []

    for trade in live_trades:
        current_price = as_float(trade.get("current_price"))
        if current_price <= 0:
            live_rows.append((trade, None))
            continue

        numbers = trade_live_numbers(trade, current_price, position_usdt)
        total_live_pnl += numbers["live_pnl"]
        total_stop_pnl += numbers["stop_pnl"]
        live_rows.append((trade, numbers))

    text = (
        "📡 <b>Открытые сделки онлайн</b>\n"
        f"Обновлено: <b>{datetime.now().strftime('%H:%M:%S')}</b>\n\n"
        f"Закрытый PnL: <b>{fmt_signed_money(closed_pnl)}</b>\n"
        f"Открытые сейчас: <b>{fmt_signed_money(total_live_pnl)}</b>\n"
        f"Если закрыть всё сейчас: <b>{fmt_signed_money(closed_pnl + total_live_pnl)}</b>\n"
        f"Если все стопы: <b>{fmt_signed_money(closed_pnl + total_stop_pnl)}</b>\n\n"
    )

    for t, numbers in live_rows:
        direction = t.get("direction", "-")
        emoji = "🟢" if direction == "LONG" else "🔴"
        stage = t.get("protection_stage") or "INITIAL"

        if numbers is None:
            text += (
                f"{emoji} <b>{t.get('symbol', '-')}</b> | <b>{direction}</b>\n"
                f"Стадия: <b>{trade_stage_label(stage)}</b>\n"
                "Текущую цену сейчас не удалось получить.\n\n"
            )
            continue

        text += (
            f"{emoji} <b>{t.get('symbol', '-')}</b> | <b>{direction}</b>\n"
            f"Стадия: <b>{trade_stage_label(stage)}</b>\n"
            f"Вход: <b>{fmt_price(numbers['entry_price'])}</b> | "
            f"Сейчас: <b>{fmt_price(t.get('current_price'))}</b>\n"
            f"PnL сейчас: <b>{fmt_signed_money(numbers['live_pnl'])}</b>\n"
            f"Если стоп: <b>{fmt_signed_money(numbers['stop_pnl'])}</b>\n"
            f"До стопа: <b>{fmt_pct(numbers['stop_distance_pct'])}</b> | "
            f"до {numbers['next_name']}: <b>{fmt_pct(numbers['next_distance_pct'])}</b>\n"
            f"{numbers['next_name']}: <b>{fmt_price(numbers['next_price'])}</b> | "
            f"Stop: <b>{fmt_price(numbers['active_stop'])}</b>\n\n"
        )

    await send_dashboard(
        message,
        text,
        reply_markup=get_trades_menu(),
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
            reply_markup=get_trades_menu(),
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
        reply_markup=get_trades_menu(),
    )


async def _send_symbol_stats(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = await scanner.refresh_symbol_stats()

    if not rows:
        await send_dashboard(
            message,
            "🪙 <b>Статистика монет</b>\n\n"
            "Пока нет закрытых сделок для расчёта.",
            reply_markup=get_stats_menu(),
        )
        return

    profitable = [x for x in rows if float(x.get("total_r") or 0.0) > 0][:10]
    losing = sorted(
        [x for x in rows if float(x.get("total_r") or 0.0) < 0],
        key=lambda x: float(x.get("total_r") or 0.0),
    )[:10]

    text = "🪙 <b>Статистика монет</b>\n\n"

    text += "✅ <b>Топ прибыльных</b>\n"
    if profitable:
        for item in profitable:
            text += (
                f"<b>{item['symbol']}</b> | "
                f"WR {item['winrate']}% | "
                f"Exp {item['expectancy']}R | "
                f"Total {item['total_r']}R | "
                f"Closed {item['closed']}\n"
            )
    else:
        text += "Нет данных.\n"

    text += "\n❌ <b>Топ убыточных</b>\n"
    if losing:
        for item in losing:
            text += (
                f"<b>{item['symbol']}</b> | "
                f"WR {item['winrate']}% | "
                f"Exp {item['expectancy']}R | "
                f"Total {item['total_r']}R | "
                f"Closed {item['closed']}\n"
            )
    else:
        text += "Нет данных.\n"

    await send_dashboard(
        message,
        text,
        reply_markup=get_stats_menu(),
    )


async def _send_side_stats(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_side_stats()

    long_stats = stats.get("LONG", {})
    short_stats = stats.get("SHORT", {})

    def side_block(title: str, item: dict) -> str:
        return (
            f"{title}\n"
            f"Signals: <b>{item.get('total', 0)}</b>\n"
            f"Closed: <b>{item.get('closed', 0)}</b>\n"
            f"Winrate: <b>{item.get('winrate', 0)}%</b>\n"
            f"Stop-rate: <b>{item.get('stop_rate', 0)}%</b>\n"
            f"Expectancy: <b>{item.get('expectancy', 0)}R</b>\n"
            f"Total R: <b>{item.get('total_r', 0)}R</b>\n"
            f"Max DD: <b>{item.get('max_drawdown', 0)}R</b>\n"
        )

    long_exp = float(long_stats.get("expectancy") or 0.0)
    short_exp = float(short_stats.get("expectancy") or 0.0)

    if int(long_stats.get("closed") or 0) == 0 and int(short_stats.get("closed") or 0) == 0:
        verdict = "Недостаточно закрытых сделок для сравнения."
    elif long_exp < short_exp:
        verdict = "Хуже сейчас: <b>LONG</b>"
    elif short_exp < long_exp:
        verdict = "Хуже сейчас: <b>SHORT</b>"
    else:
        verdict = "LONG и SHORT сейчас примерно равны по expectancy."

    await send_dashboard(
        message,
        "↕️ <b>LONG / SHORT статистика</b>\n\n"
        f"{side_block('🟢 <b>LONG</b>', long_stats)}\n"
        f"{side_block('🔴 <b>SHORT</b>', short_stats)}\n"
        f"📌 {verdict}\n\n"
        "Фильтр слабой стороны: "
        f"<b>{'ON' if Config.SIDE_QUALITY_FILTER_ENABLED else 'OFF'}</b>",
        reply_markup=get_stats_menu(),
    )


async def _send_equity(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = await scanner.trade_tracker.get_equity_curve()

    if not rows:
        await send_dashboard(
            message,
            "📉 <b>Equity Curve</b>\n\n"
            "Пока нет закрытых сделок.",
            reply_markup=get_stats_menu(),
        )
        return

    text = "📉 <b>Equity Curve</b>\n\n"
    text += f"Текущий итог: <b>{rows[-1]['equity_r']}R</b>\n\n"

    for item in rows[-12:]:
        sign = "+" if float(item["result_r"]) > 0 else ""
        text += (
            f"{item['closed_at'][:10]} | "
            f"<b>{item['symbol']}</b> | "
            f"{sign}{item['result_r']}R | "
            f"Eq {item['equity_r']}R\n"
        )

    await send_dashboard(
        message,
        text,
        reply_markup=get_stats_menu(),
    )


async def _send_symbols(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    whitelist = await scanner.get_symbol_whitelist()

    if not whitelist:
        best = await scanner.get_best_pairs(
            min_closed=Config.AUTO_WHITELIST_MIN_CLOSED_TRADES,
            limit=Config.AUTO_WHITELIST_SIZE,
        )

        if not best:
            await send_dashboard(
                message,
                "🪙 <b>Монеты</b>\n\n"
                "Авто-WhiteList ещё не сформирован: нужно больше закрытых сделок по символам.",
                reply_markup=get_main_menu(),
            )
            return

        whitelist = best

    text = "🪙 <b>Авто-WhiteList</b>\n\n"

    for index, item in enumerate(whitelist[: Config.AUTO_WHITELIST_SIZE], start=1):
        text += (
            f"{index}. <b>{item['symbol']}</b> | "
            f"Exp {item['expectancy']}R | "
            f"WR {item['winrate']}% | "
            f"Total {item['total_r']}R | "
            f"Closed {item.get('closed_count', item.get('closed', 0))}\n"
        )

    await send_dashboard(
        message,
        text,
        reply_markup=get_main_menu(),
    )


async def _send_open_orders(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]

    try:
        orders = await scanner.get_open_orders()
    except Exception as error:
        await send_dashboard(
            message,
            "🧾 <b>Открытые ордера</b>\n\n"
            f"Не удалось получить ордера: <code>{error}</code>",
            reply_markup=get_trades_menu(),
        )
        return

    if not orders:
        await send_dashboard(
            message,
            "🧾 <b>Открытые ордера</b>\n\n"
            "Нет данных или автоторговля выключена.",
            reply_markup=get_trades_menu(),
        )
        return

    text = "🧾 <b>Открытые ордера</b>\n\n"

    for order in orders[:15]:
        text += (
            f"<b>{order.get('symbol', '-')}</b> | "
            f"{order.get('side', '-')} | "
            f"{order.get('type', order.get('orderType', '-'))}\n"
            f"Price: <b>{fmt_price(order.get('price') or order.get('stopPrice') or order.get('triggerPrice'))}</b> | "
            f"Qty: <b>{order.get('origQty', order.get('quantity', '-'))}</b>\n\n"
        )

    await send_dashboard(
        message,
        text,
        reply_markup=get_trades_menu(),
    )


async def _export_csv(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    path = await scanner.trade_tracker.export_csv()
    await message.answer_document(FSInputFile(path))


async def _export_excel(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    path = await scanner.trade_tracker.export_excel()
    await message.answer_document(FSInputFile(path))


async def _send_version(message: Message):
    await send_dashboard(
        message,
        "🏷 <b>Версия</b>\n\n"
        f"Crypto Signal Bot Pro: <b>{Config.APP_VERSION}</b>\n"
        f"Mode: <b>{Config.STRATEGY_MODE}</b>\n"
        f"Auto WhiteList: <b>{'ON' if Config.AUTO_WHITELIST_ENABLED else 'OFF'}</b>",
        reply_markup=get_admin_menu(),
    )


async def _refresh_whitelist(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = await scanner.refresh_symbol_whitelist()

    await send_dashboard(
        message,
        "🔄 <b>WhiteList обновлён</b>\n\n"
        f"Символов: <b>{len(rows)}</b>",
        reply_markup=get_admin_menu(),
    )


async def _reset_stats(message: Message, dispatcher: Dispatcher):
    if not await guard_admin(message):
        return

    scanner = dispatcher["scanner"]
    await scanner.trade_tracker.reset_stats()

    await send_dashboard(
        message,
        "♻️ <b>Статистика сброшена</b>\n\n"
        "Сигналы в истории сохранены, расчёт статистики начат заново.",
        reply_markup=get_admin_menu(),
    )


async def _reset_db(message: Message, dispatcher: Dispatcher):
    if not await guard_admin(message):
        return

    scanner = dispatcher["scanner"]
    await scanner.trade_tracker.reset_db()

    await send_dashboard(
        message,
        "🧹 <b>База очищена</b>\n\n"
        "Состояние, сигналы, сделки, whitelist и экспортная статистика очищены.",
        reply_markup=get_admin_menu(),
    )


async def _restart_bot(message: Message):
    if not await guard_admin(message):
        return

    await send_dashboard(
        message,
        "🔁 <b>Перезапуск</b>\n\n"
        "Процесс будет остановлен, платформа должна поднять его заново.",
        reply_markup=get_admin_menu(),
    )
    await asyncio.sleep(1)
    os._exit(0)


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


@router.message(Command("health"))
async def health_handler(message: Message, dispatcher: Dispatcher):
    await _send_status(message, dispatcher)


@router.message(Command("stats"))
async def stats_handler(message: Message, dispatcher: Dispatcher):
    await _send_signal_stats(message, dispatcher)


@router.message(Command("stats_symbols"))
async def stats_symbols_handler(message: Message, dispatcher: Dispatcher):
    await _send_symbol_stats(message, dispatcher)


@router.message(Command("stats_sides"))
async def stats_sides_handler(message: Message, dispatcher: Dispatcher):
    await _send_side_stats(message, dispatcher)


@router.message(Command("equity"))
async def equity_handler(message: Message, dispatcher: Dispatcher):
    await _send_equity(message, dispatcher)


@router.message(Command("lastsignals"))
async def lastsignals_handler(message: Message, dispatcher: Dispatcher):
    await _send_last_signals(message, dispatcher)


@router.message(Command("open"))
async def open_handler(message: Message, dispatcher: Dispatcher):
    await _send_open_trades(message, dispatcher)


@router.message(Command("open_trades"))
async def open_trades_handler(message: Message, dispatcher: Dispatcher):
    await _send_open_trades(message, dispatcher)


@router.message(Command("open_orders"))
async def open_orders_handler(message: Message, dispatcher: Dispatcher):
    await _send_open_orders(message, dispatcher)


@router.message(Command("history"))
async def history_handler(message: Message, dispatcher: Dispatcher):
    await _send_history(message, dispatcher)


@router.message(Command("symbols"))
async def symbols_handler(message: Message, dispatcher: Dispatcher):
    await _send_symbols(message, dispatcher)


@router.message(Command("version"))
async def version_handler(message: Message):
    await _send_version(message)


@router.message(Command("reset_stats"))
async def reset_stats_handler(message: Message, dispatcher: Dispatcher):
    await _reset_stats(message, dispatcher)


@router.message(Command("reset_db"))
async def reset_db_handler(message: Message, dispatcher: Dispatcher):
    text = message.text or ""
    if "confirm" not in text.lower():
        await send_dashboard(
            message,
            "🧹 <b>Сброс базы</b>\n\n"
            "Для полной очистки нажми кнопку подтверждения.",
            reply_markup=get_reset_db_confirm_menu(),
        )
        return

    await _reset_db(message, dispatcher)


@router.message(Command("restart"))
async def restart_handler(message: Message):
    await _restart_bot(message)


# =====================
# BUTTONS
# =====================

@router.message(lambda m: m.text in {"📊 Статус", "🟢 Health", "🟢 Система"})
async def btn_status(message: Message, dispatcher: Dispatcher):
    await _send_status(message, dispatcher)


@router.message(lambda m: m.text == "📈 Статистика")
async def btn_stats_menu(message: Message):
    await send_dashboard(
        message,
        "📈 <b>Статистика</b>\n\n"
        "Выбери раздел:",
        reply_markup=get_stats_menu(),
    )


@router.message(lambda m: m.text == "📊 Общая статистика")
async def btn_stats(message: Message, dispatcher: Dispatcher):
    await _send_signal_stats(message, dispatcher)


@router.message(lambda m: m.text == "🪙 Статистика монет")
async def btn_stats_symbols(message: Message, dispatcher: Dispatcher):
    await _send_symbol_stats(message, dispatcher)


@router.message(lambda m: m.text == "↕️ LONG / SHORT")
async def btn_stats_sides(message: Message, dispatcher: Dispatcher):
    await _send_side_stats(message, dispatcher)


@router.message(lambda m: m.text == "📉 Equity Curve")
async def btn_equity(message: Message, dispatcher: Dispatcher):
    await _send_equity(message, dispatcher)


@router.message(lambda m: m.text == "📌 Сигналы")
async def btn_signals(message: Message, dispatcher: Dispatcher):
    await _send_last_signals(message, dispatcher)


@router.message(lambda m: m.text == "🪙 Монеты")
async def btn_symbols(message: Message, dispatcher: Dispatcher):
    await _send_symbols(message, dispatcher)


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


@router.message(lambda m: m.text == "🧾 Ордера")
async def btn_orders(message: Message, dispatcher: Dispatcher):
    await _send_open_orders(message, dispatcher)


@router.message(lambda m: m.text == "📜 История")
async def btn_history(message: Message, dispatcher: Dispatcher):
    await _send_history(message, dispatcher)


@router.message(lambda m: m.text == "📤 Экспорт")
async def btn_export_menu(message: Message):
    await send_dashboard(
        message,
        "📤 <b>Экспорт</b>\n\n"
        "Выбери формат:",
        reply_markup=get_export_menu(),
    )


@router.message(lambda m: m.text == "📄 CSV")
async def btn_export_csv(message: Message, dispatcher: Dispatcher):
    await _export_csv(message, dispatcher)


@router.message(lambda m: m.text == "📊 Excel")
async def btn_export_excel(message: Message, dispatcher: Dispatcher):
    await _export_excel(message, dispatcher)


@router.message(lambda m: m.text == "⚙️ Админ")
async def btn_admin_menu(message: Message):
    if not await guard_admin(message):
        return

    await send_dashboard(
        message,
        "⚙️ <b>Админ</b>\n\n"
        "Выбери действие:",
        reply_markup=get_admin_menu(),
    )


@router.message(lambda m: m.text == "🏷 Версия")
async def btn_version(message: Message):
    await _send_version(message)


@router.message(lambda m: m.text == "🔄 Обновить WhiteList")
async def btn_refresh_whitelist(message: Message, dispatcher: Dispatcher):
    if not await guard_admin(message):
        return

    await _refresh_whitelist(message, dispatcher)


@router.message(lambda m: m.text in {"♻️ Reset Stats", "♻️ Сброс статистики"})
async def btn_reset_stats(message: Message, dispatcher: Dispatcher):
    await _reset_stats(message, dispatcher)


@router.message(lambda m: m.text in {"🧹 Reset DB", "🧹 Сброс базы"})
async def btn_reset_db_prompt(message: Message):
    if not await guard_admin(message):
        return

    await send_dashboard(
        message,
        "🧹 <b>Сброс базы</b>\n\n"
        "Это полностью очистит базу бота. Подтверди действие отдельной кнопкой.",
        reply_markup=get_reset_db_confirm_menu(),
    )


@router.message(lambda m: m.text in {"✅ Подтвердить Reset DB", "✅ Подтвердить сброс базы"})
async def btn_reset_db_confirm(message: Message, dispatcher: Dispatcher):
    await _reset_db(message, dispatcher)


@router.message(lambda m: m.text in {"🔁 Restart", "🔁 Перезапуск"})
async def btn_restart(message: Message):
    await _restart_bot(message)


@router.message(lambda m: m.text == "⬅️ Назад")
async def btn_back(message: Message):
    await send_dashboard(
        message,
        "👇 <b>Главное меню</b>\n\n"
        "Выбери действие:",
        reply_markup=get_main_menu(),
    )


@router.message(Command("export"))
async def export_handler(message: Message, dispatcher: Dispatcher):
    await _export_csv(message, dispatcher)

@router.message(Command("export_csv"))
async def export_csv_handler(message: Message, dispatcher: Dispatcher):
    await _export_csv(message, dispatcher)


@router.message(Command("export_excel"))
async def export_excel_handler(message: Message, dispatcher: Dispatcher):
    await _export_excel(message, dispatcher)
