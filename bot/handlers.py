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

    return f"{value:.2f}%"


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


async def build_portfolio_snapshot(scanner, limit: int = 10) -> dict:
    trades = await scanner.get_paper_open_trades()
    paper_stats = await scanner.get_paper_stats()

    margin_usdt = as_float(paper_stats.get("trade_margin_usdt")) or Config.AUTO_TRADE_USDT
    leverage = int(paper_stats.get("trade_leverage") or Config.AUTO_TRADE_LEVERAGE)
    position_usdt = as_float(paper_stats.get("trade_position_usdt")) or (margin_usdt * leverage)

    async def enrich_trade(trade: dict) -> dict:
        trade = dict(trade)
        try:
            trade["current_price"] = await scanner.execution.get_mark_price(trade["symbol"])
        except Exception as error:
            trade["current_price_error"] = str(error)
        return trade

    live_trades = await asyncio.gather(*(enrich_trade(t) for t in trades[:limit]))

    total_live_pnl = 0.0
    total_stop_pnl = 0.0
    exposure_usdt = 0.0
    margin_used_usdt = 0.0
    protected_count = 0
    long_count = 0
    short_count = 0
    rows: list[tuple[dict, dict | None]] = []

    for trade in live_trades:
        stage = trade.get("protection_stage") or "INITIAL"
        remaining_share = trade_remaining_share(stage)
        exposure_usdt += position_usdt * remaining_share
        margin_used_usdt += margin_usdt * remaining_share

        if stage in {"TP1_HIT", "TP2_HIT"}:
            protected_count += 1

        if trade.get("direction") == "LONG":
            long_count += 1
        elif trade.get("direction") == "SHORT":
            short_count += 1

        current_price = as_float(trade.get("current_price"))
        if current_price <= 0:
            entry_price = trade_entry_price(trade)
            active_stop = as_float(trade.get("active_stop_loss") or trade.get("stop_loss"))
            realized_pnl = trade_realized_partial_pnl(trade, position_usdt, entry_price)
            stop_move_pct = trade_move_pct(trade.get("direction", "-"), entry_price, active_stop)
            total_stop_pnl += realized_pnl + position_usdt * remaining_share * stop_move_pct
            rows.append((trade, None))
            continue

        numbers = trade_live_numbers(trade, current_price, position_usdt)
        total_live_pnl += numbers["live_pnl"]
        total_stop_pnl += numbers["stop_pnl"]
        rows.append((trade, numbers))

    closed_pnl = as_float(paper_stats.get("pnl_usdt"))
    net_pnl = closed_pnl + total_live_pnl
    worst_case_pnl = closed_pnl + total_stop_pnl
    balance = as_float(paper_stats.get("balance"))
    open_risk = as_float(paper_stats.get("open_risk_usdt"))
    risk_limit = balance * Config.MAX_TOTAL_OPEN_RISK_PCT if balance > 0 else 0.0
    risk_load = (open_risk / risk_limit * 100) if risk_limit > 0 else 0.0

    if long_count and short_count:
        skew = f"LONG {long_count} / SHORT {short_count}"
    elif long_count:
        skew = f"{long_count} LONG"
    elif short_count:
        skew = f"{short_count} SHORT"
    else:
        skew = "нет"

    return {
        "paper_stats": paper_stats,
        "rows": rows,
        "closed_pnl": round(closed_pnl, 2),
        "floating_pnl": round(total_live_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "worst_case_pnl": round(worst_case_pnl, 2),
        "open_count": len(trades),
        "protected_count": protected_count,
        "margin_usdt": round(margin_usdt, 2),
        "leverage": leverage,
        "position_usdt": round(position_usdt, 2),
        "margin_used_usdt": round(margin_used_usdt, 2),
        "exposure_usdt": round(exposure_usdt, 2),
        "open_risk_usdt": round(open_risk, 2),
        "risk_limit_usdt": round(risk_limit, 2),
        "risk_load_pct": round(risk_load, 2),
        "long_count": long_count,
        "short_count": short_count,
        "skew": skew,
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
    heartbeat = await scanner.get_heartbeat()
    last_cycle = heartbeat.get("last_cycle", {})

    await send_dashboard(
        message,
        "⚙️ <b>Система</b>\n\n"
        "Статус: <b>активен</b>\n"
        f"Режим: <b>{heartbeat.get('mode')}</b>\n"
        f"Автоторговля: <b>{'включена' if Config.AUTO_TRADE else 'выключена'}</b>\n"
        f"Сканирование: <b>{heartbeat.get('scan_interval')} сек</b>\n"
        f"Последний цикл: <b>{last_cycle.get('started_at') or '-'}</b>\n"
        f"Проверено пар: <b>{last_cycle.get('symbols_checked', 0)}</b>\n"
        f"Сигналов в цикле: <b>{last_cycle.get('signals_found', 0)}</b>\n\n"
        "Параметры сделки\n"
        f"Маржа: <b>{fmt_money(Config.AUTO_TRADE_USDT)}</b>\n"
        f"Плечо: <b>x{Config.AUTO_TRADE_LEVERAGE}</b>\n"
        f"Позиция: <b>{fmt_money(Config.AUTO_TRADE_USDT * Config.AUTO_TRADE_LEVERAGE)}</b>",
        reply_markup=get_main_menu(),
    )


# =====================
# STATS
# =====================

async def _send_summary(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    snapshot = await build_portfolio_snapshot(scanner)
    period = stats_period_label()

    await send_dashboard(
        message,
        f"📊 <b>Сводка</b>\n"
        f"Период: <b>{period}</b>\n\n"
        f"Зафиксировано: <b>{fmt_signed_money(snapshot['closed_pnl'])}</b>\n"
        f"Плавающий PnL: <b>{fmt_signed_money(snapshot['floating_pnl'])}</b>\n"
        f"Итог сейчас: <b>{fmt_signed_money(snapshot['net_pnl'])}</b>\n"
        f"Худший сценарий: <b>{fmt_signed_money(snapshot['worst_case_pnl'])}</b>\n\n"
        f"Позиции: <b>{snapshot['open_count']}</b>\n"
        f"Защищено: <b>{snapshot['protected_count']}</b>\n"
        f"Маржа остатка: <b>{fmt_money(snapshot['margin_used_usdt'])}</b>\n"
        f"Объём остатка: <b>{fmt_money(snapshot['exposure_usdt'])}</b>\n"
        f"Открытый риск: <b>{fmt_money(snapshot['open_risk_usdt'])}</b>",
        reply_markup=get_main_menu(),
    )


async def _send_finances(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    stats = await scanner.get_stats()
    snapshot = await build_portfolio_snapshot(scanner)
    period = stats_period_label()

    await send_dashboard(
        message,
        f"💵 <b>Финансы</b>\n"
        f"Период: <b>{period}</b>\n\n"
        f"Зафиксировано: <b>{fmt_signed_money(snapshot['closed_pnl'])}</b>\n"
        f"Плавающий PnL: <b>{fmt_signed_money(snapshot['floating_pnl'])}</b>\n"
        f"Итог сейчас: <b>{fmt_signed_money(snapshot['net_pnl'])}</b>\n"
        f"Худший сценарий: <b>{fmt_signed_money(snapshot['worst_case_pnl'])}</b>\n\n"
        f"Закрыто сделок: <b>{stats['closed']}</b>\n"
        f"В плюс: <b>{stats['wins']}</b>\n"
        f"В минус: <b>{stats['losses']}</b>\n"
        f"Результат: <b>{stats['total_r']}R</b>\n"
        f"Средняя сделка: <b>{stats['expectancy']}R</b>",
        reply_markup=get_main_menu(),
    )


async def _send_risk(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    snapshot = await build_portfolio_snapshot(scanner)

    await send_dashboard(
        message,
        "🛡 <b>Риск</b>\n\n"
        f"Открытый риск: <b>{fmt_money(snapshot['open_risk_usdt'])}</b>\n"
        f"Лимит риска: <b>{fmt_money(snapshot['risk_limit_usdt'])}</b>\n"
        f"Загрузка риска: <b>{fmt_pct(snapshot['risk_load_pct'])}</b>\n\n"
        f"Худший сценарий: <b>{fmt_signed_money(snapshot['worst_case_pnl'])}</b>\n"
        f"Позиции: <b>{snapshot['open_count']} / {Config.MAX_OPEN_TRADES}</b>\n"
        f"Защищено: <b>{snapshot['protected_count']}</b>\n"
        f"Перекос: <b>{snapshot['skew']}</b>\n\n"
        f"Маржа остатка: <b>{fmt_money(snapshot['margin_used_usdt'])}</b>\n"
        f"Объём остатка: <b>{fmt_money(snapshot['exposure_usdt'])}</b>",
        reply_markup=get_main_menu(),
    )


async def _send_signal_stats(message: Message, dispatcher: Dispatcher):
    await _send_finances(message, dispatcher)


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
    snapshot = await build_portfolio_snapshot(scanner)
    live_rows = snapshot["rows"]

    if not live_rows:
        await send_dashboard(
            message,
            "📈 <b>Позиции</b>\n\n"
            "Нет открытых позиций.",
            reply_markup=get_trades_menu(),
        )
        return

    text = (
        "📈 <b>Позиции</b>\n"
        f"Обновлено: <b>{datetime.now().strftime('%H:%M:%S')}</b>\n\n"
        f"Плавающий PnL: <b>{fmt_signed_money(snapshot['floating_pnl'])}</b>\n"
        f"Итог сейчас: <b>{fmt_signed_money(snapshot['net_pnl'])}</b>\n"
        f"Худший сценарий: <b>{fmt_signed_money(snapshot['worst_case_pnl'])}</b>\n\n"
    )

    for t, numbers in live_rows:
        direction = t.get("direction", "-")
        emoji = "🟢" if direction == "LONG" else "🔴"
        stage = t.get("protection_stage") or "INITIAL"

        if numbers is None:
            text += (
                f"{emoji} <b>{t.get('symbol', '-')}</b> | <b>{direction}</b>\n"
                f"Статус: <b>{trade_stage_label(stage)}</b>\n"
                "Текущую цену сейчас не удалось получить.\n\n"
            )
            continue

        text += (
            f"{emoji} <b>{t.get('symbol', '-')}</b> | <b>{direction}</b>\n"
            f"Статус: <b>{trade_stage_label(stage)}</b>\n"
            f"Вход: <b>{fmt_price(numbers['entry_price'])}</b> | "
            f"Сейчас: <b>{fmt_price(t.get('current_price'))}</b>\n"
            f"Плавающий PnL: <b>{fmt_signed_money(numbers['live_pnl'])}</b>\n"
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
            "📜 <b>Журнал</b>\n\n"
            "Закрытых сделок пока нет.",
            reply_markup=get_trades_menu(),
        )
        return

    text = "📜 <b>Журнал</b>\n\n"

    for t in trades:
        result_r = float(t.get("result_r") or 0)
        result_usdt = as_float(t.get("result_usdt"))

        if result_r > 0:
            emoji = "✅"
        elif result_r < 0:
            emoji = "❌"
        else:
            emoji = "⚪️"

        text += (
            f"{emoji} <b>{t.get('symbol', '-')}</b> "
            f"{t.get('direction', '-')} | "
            f"<b>{fmt_signed_money(result_usdt)}</b> | "
            f"{fmt_r(result_r)} | "
            f"{t.get('close_reason', '-')}\n"
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
                f"Винрейт {item['winrate']}% | "
                f"Средняя {item['expectancy']}R | "
                f"Итог {item['total_r']}R | "
                f"Закрыто {item['closed']}\n"
            )
    else:
        text += "Нет данных.\n"

    text += "\n❌ <b>Топ убыточных</b>\n"
    if losing:
        for item in losing:
            text += (
                f"<b>{item['symbol']}</b> | "
                f"Винрейт {item['winrate']}% | "
                f"Средняя {item['expectancy']}R | "
                f"Итог {item['total_r']}R | "
                f"Закрыто {item['closed']}\n"
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
            f"Сигналов: <b>{item.get('total', 0)}</b>\n"
            f"Закрыто: <b>{item.get('closed', 0)}</b>\n"
            f"Винрейт: <b>{item.get('winrate', 0)}%</b>\n"
            f"Стоп-рейт: <b>{item.get('stop_rate', 0)}%</b>\n"
            f"Средняя сделка: <b>{item.get('expectancy', 0)}R</b>\n"
            f"Итог: <b>{item.get('total_r', 0)}R</b>\n"
            f"Просадка: <b>{item.get('max_drawdown', 0)}R</b>\n"
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
        verdict = "LONG и SHORT сейчас примерно равны по средней сделке."

    await send_dashboard(
        message,
        "↕️ <b>LONG / SHORT статистика</b>\n\n"
        f"{side_block('🟢 <b>LONG</b>', long_stats)}\n"
        f"{side_block('🔴 <b>SHORT</b>', short_stats)}\n"
        f"📌 {verdict}\n\n"
        "Фильтр слабой стороны: "
        f"<b>{'включен' if Config.SIDE_QUALITY_FILTER_ENABLED else 'выключен'}</b>",
        reply_markup=get_stats_menu(),
    )


async def _send_equity(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = await scanner.trade_tracker.get_equity_curve()

    if not rows:
        await send_dashboard(
            message,
            "📉 <b>Кривая доходности</b>\n\n"
            "Пока нет закрытых сделок.",
            reply_markup=get_stats_menu(),
        )
        return

    text = "📉 <b>Кривая доходности</b>\n\n"
    text += f"Текущий итог: <b>{rows[-1]['equity_r']}R</b>\n\n"

    for item in rows[-12:]:
        sign = "+" if float(item["result_r"]) > 0 else ""
        text += (
            f"{item['closed_at'][:10]} | "
            f"<b>{item['symbol']}</b> | "
            f"{sign}{item['result_r']}R | "
            f"Итог {item['equity_r']}R\n"
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
                "Список монет ещё не сформирован: нужно больше закрытых сделок по символам.",
                reply_markup=get_main_menu(),
            )
            return

        whitelist = best

    text = "🪙 <b>Список монет</b>\n\n"

    for index, item in enumerate(whitelist[: Config.AUTO_WHITELIST_SIZE], start=1):
        text += (
            f"{index}. <b>{item['symbol']}</b> | "
            f"Средняя {item['expectancy']}R | "
            f"Винрейт {item['winrate']}% | "
            f"Итог {item['total_r']}R | "
            f"Закрыто {item.get('closed_count', item.get('closed', 0))}\n"
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
            f"Цена: <b>{fmt_price(order.get('price') or order.get('stopPrice') or order.get('triggerPrice'))}</b> | "
            f"Количество: <b>{order.get('origQty', order.get('quantity', '-'))}</b>\n\n"
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
        f"Режим: <b>{Config.STRATEGY_MODE}</b>\n"
        f"Автосписок монет: <b>{'включен' if Config.AUTO_WHITELIST_ENABLED else 'выключен'}</b>",
        reply_markup=get_admin_menu(),
    )


async def _refresh_whitelist(message: Message, dispatcher: Dispatcher):
    scanner = dispatcher["scanner"]
    rows = await scanner.refresh_symbol_whitelist()

    await send_dashboard(
        message,
        "🔄 <b>Список монет обновлён</b>\n\n"
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
        "📊 <b>Панель управления</b>\n\n"
        "Выбери раздел.",
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
    await _send_summary(message, dispatcher)


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

@router.message(lambda m: m.text in {"📊 Статус", "🟢 Система"})
async def btn_status(message: Message, dispatcher: Dispatcher):
    await _send_status(message, dispatcher)


@router.message(lambda m: m.text == "📊 Сводка")
async def btn_summary(message: Message, dispatcher: Dispatcher):
    await _send_summary(message, dispatcher)


@router.message(lambda m: m.text == "💵 Финансы")
async def btn_finances(message: Message, dispatcher: Dispatcher):
    await _send_finances(message, dispatcher)


@router.message(lambda m: m.text == "🛡 Риск")
async def btn_risk(message: Message, dispatcher: Dispatcher):
    await _send_risk(message, dispatcher)


@router.message(lambda m: m.text == "⚙️ Система")
async def btn_system(message: Message, dispatcher: Dispatcher):
    await _send_status(message, dispatcher)


@router.message(lambda m: m.text == "📈 Статистика")
async def btn_stats_menu(message: Message):
    await send_dashboard(
        message,
        "📈 <b>Статистика</b>\n\n"
        "Выбери раздел.",
        reply_markup=get_stats_menu(),
    )


@router.message(lambda m: m.text == "📊 Общая статистика")
async def btn_stats(message: Message, dispatcher: Dispatcher):
    await _send_summary(message, dispatcher)


@router.message(lambda m: m.text == "🪙 Статистика монет")
async def btn_stats_symbols(message: Message, dispatcher: Dispatcher):
    await _send_symbol_stats(message, dispatcher)


@router.message(lambda m: m.text == "↕️ LONG / SHORT")
async def btn_stats_sides(message: Message, dispatcher: Dispatcher):
    await _send_side_stats(message, dispatcher)


@router.message(lambda m: m.text == "📉 Кривая доходности")
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
        "📈 <b>Сделки</b>\n\n"
        "Выбери раздел.",
        reply_markup=get_trades_menu(),
    )


@router.message(lambda m: m.text in {"📂 Открытые", "📈 Позиции"})
async def btn_open(message: Message, dispatcher: Dispatcher):
    await _send_open_trades(message, dispatcher)


@router.message(lambda m: m.text == "🧾 Ордера")
async def btn_orders(message: Message, dispatcher: Dispatcher):
    await _send_open_orders(message, dispatcher)


@router.message(lambda m: m.text in {"📜 История", "📜 Журнал"})
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
        "Выбери действие.",
        reply_markup=get_admin_menu(),
    )


@router.message(lambda m: m.text == "🏷 Версия")
async def btn_version(message: Message):
    await _send_version(message)


@router.message(lambda m: m.text == "🔄 Обновить список монет")
async def btn_refresh_whitelist(message: Message, dispatcher: Dispatcher):
    if not await guard_admin(message):
        return

    await _refresh_whitelist(message, dispatcher)


@router.message(lambda m: m.text == "♻️ Сброс статистики")
async def btn_reset_stats(message: Message, dispatcher: Dispatcher):
    await _reset_stats(message, dispatcher)


@router.message(lambda m: m.text == "🧹 Сброс базы")
async def btn_reset_db_prompt(message: Message):
    if not await guard_admin(message):
        return

    await send_dashboard(
        message,
        "🧹 <b>Сброс базы</b>\n\n"
        "Это полностью очистит базу бота. Подтверди действие отдельной кнопкой.",
        reply_markup=get_reset_db_confirm_menu(),
    )


@router.message(lambda m: m.text == "✅ Подтвердить сброс базы")
async def btn_reset_db_confirm(message: Message, dispatcher: Dispatcher):
    await _reset_db(message, dispatcher)


@router.message(lambda m: m.text == "🔁 Перезапуск")
async def btn_restart(message: Message):
    await _restart_bot(message)


@router.message(lambda m: m.text == "⬅️ Назад")
async def btn_back(message: Message):
    await send_dashboard(
        message,
        "📊 <b>Панель управления</b>\n\n"
        "Выбери раздел.",
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
