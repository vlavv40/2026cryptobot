from aiogram import Bot


def _fmt_price(value: float) -> str:
    try:
        value = float(value)
    except Exception:
        return "-"

    if value == 0:
        return "0"

    if abs(value) >= 1000:
        return f"{value:,.2f}".replace(",", " ")
    if abs(value) >= 100:
        return f"{value:.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if abs(value) >= 0.01:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    return f"{value:.8f}".rstrip("0").rstrip(".")


def _fmt_r(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "-"

    if value > 0:
        return f"+{value:.2f}R"
    return f"{value:.2f}R"


def _direction_emoji(direction: str) -> str:
    return "🟢" if direction == "LONG" else "🔴"


def _signal_header(signal_type: str, direction: str) -> str:
    side = "LONG" if direction == "LONG" else "SHORT"

    if signal_type == "STRONG":
        return f"🔥 <b>STRONG {side}</b>"

    return f"⚡️ <b>SETUP {side}</b>"


def format_signal(signal) -> str:
    signal_type = getattr(signal, "signal_type", "STRONG")
    direction = signal.direction
    emoji = _direction_emoji(direction)

    reasons = signal.reasons[:6]
    reasons_text = "\n".join(f"• {reason}" for reason in reasons) if reasons else "• условия подтверждены"

    position_hint = "Стандартный вход"
    if signal_type == "SETUP":
        position_hint = "Осторожный вход / сниженный риск"

    return (
        f"{_signal_header(signal_type, direction)}\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"{emoji} <b>#{signal.symbol}</b>\n"
        f"Направление: <b>{direction}</b>\n"
        f"Тип: <b>{signal_type}</b>\n"
        f"Score: <b>{signal.score}/10</b>\n\n"
        f"🎯 <b>Зона входа</b>\n"
        f"<code>{_fmt_price(signal.entry_min)} - {_fmt_price(signal.entry_max)}</code>\n\n"
        f"🛑 <b>Stop</b>\n"
        f"<code>{_fmt_price(signal.stop_loss)}</code>\n\n"
        f"🏁 <b>Цели</b>\n"
        f"TP1: <code>{_fmt_price(signal.tp1)}</code>\n"
        f"TP2: <code>{_fmt_price(signal.tp2)}</code>\n"
        f"TP3: <code>{_fmt_price(signal.tp3)}</code>\n\n"
        f"📌 <b>Риск</b>\n"
        f"{position_hint}\n\n"
        f"🧠 <b>Причины</b>\n"
        f"{reasons_text}\n\n"
        f"━━━━━━━━━━━━━━"
    )


def format_result_message(item: dict) -> str:
    status = item["status"]
    symbol = item["symbol"]
    direction = item["direction"]
    signal_type = item.get("signal_type", "UNKNOWN")
    realized_r = item.get("realized_r")
    stop_loss = item.get("active_stop_loss") or item["stop_loss"]

    if status == "STOP_HIT":
        icon = "❌"
        title = "STOP HIT"
        subtitle = "Сделка закрыта по стопу"
    elif status == "TP1_HIT":
        icon = "✅"
        title = "TP1 HIT"
        subtitle = "Первая цель достигнута"
    elif status == "TP2_HIT":
        icon = "💰"
        title = "TP2 HIT"
        subtitle = "Вторая цель достигнута"
    elif status == "TP3_HIT":
        icon = "🚀"
        title = "TP3 HIT"
        subtitle = "Максимальная цель достигнута"
    else:
        icon = "📌"
        title = status
        subtitle = "Сделка обновлена"

    return (
        f"{icon} <b>{title}</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"<b>{subtitle}</b>\n\n"
        f"{_direction_emoji(direction)} <b>#{symbol}</b>\n"
        f"Направление: <b>{direction}</b>\n"
        f"Тип: <b>{signal_type}</b>\n"
        f"Результат: <b>{_fmt_r(realized_r)}</b>\n\n"
        f"🎯 <b>Вход</b>\n"
        f"<code>{_fmt_price(float(item['entry_min']))} - {_fmt_price(float(item['entry_max']))}</code>\n\n"
        f"🛑 <b>Stop</b>\n"
        f"<code>{_fmt_price(float(stop_loss))}</code>\n\n"
        f"🏁 <b>Цели</b>\n"
        f"TP1: <code>{_fmt_price(float(item['tp1']))}</code>\n"
        f"TP2: <code>{_fmt_price(float(item['tp2']))}</code>\n"
        f"TP3: <code>{_fmt_price(float(item['tp3']))}</code>\n\n"
        f"━━━━━━━━━━━━━━"
    )


def format_trade_update_message(item: dict, status: str, auto_managed: bool = True) -> str:
    symbol = item["symbol"]
    direction = item["direction"]
    entry_price = item.get("entry_price")
    breakeven_price = (
        float(entry_price)
        if entry_price is not None
        else (float(item["entry_min"]) + float(item["entry_max"])) / 2.0
    )

    if status == "TP1_HIT":
        title = "TP1 HIT"
        subtitle = "70% позиции закрыто, стоп остатка перенесен в безубыток"
        if not auto_managed:
            subtitle = "Первая цель достигнута, сигнал остается в сопровождении"
        stop_loss = breakeven_price
        remaining_targets = (
            f"TP2: <code>{_fmt_price(float(item['tp2']))}</code>\n"
            f"TP3: <code>{_fmt_price(float(item['tp3']))}</code>\n\n"
        )
    elif status == "TP2_HIT":
        title = "TP2 HIT"
        subtitle = "Еще 20% позиции закрыто, стоп остатка перенесен на TP1"
        if not auto_managed:
            subtitle = "Вторая цель достигнута, сигнал остается в сопровождении"
        stop_loss = item["tp1"]
        remaining_targets = (
            f"TP3: <code>{_fmt_price(float(item['tp3']))}</code>\n\n"
        )
    else:
        title = status
        subtitle = "Сопровождение позиции обновлено"
        stop_loss = item.get("active_stop_loss") or item["stop_loss"]
        remaining_targets = (
            f"TP2: <code>{_fmt_price(float(item['tp2']))}</code>\n"
            f"TP3: <code>{_fmt_price(float(item['tp3']))}</code>\n\n"
        )

    return (
        f"✅ <b>{title}</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"<b>{subtitle}</b>\n\n"
        f"{_direction_emoji(direction)} <b>#{symbol}</b>\n"
        f"Направление: <b>{direction}</b>\n\n"
        f"🛑 <b>Новый Stop</b>\n"
        f"<code>{_fmt_price(float(stop_loss))}</code>\n\n"
        f"🏁 <b>Остались цели</b>\n"
        f"{remaining_targets}"
        f"━━━━━━━━━━━━━━"
    )


async def send_text_to_all(bot: Bot, chat_ids: list[str], text: str):
    for chat_id in chat_ids:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception:
            continue


async def send_signal(bot: Bot, chat_ids: list[str], signal):
    await send_text_to_all(bot, chat_ids, format_signal(signal))
