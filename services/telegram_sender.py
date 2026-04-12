from aiogram import Bot


def _fmt_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.2f}".replace(",", " ")
    if value >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def format_signal(signal) -> str:
    reasons = signal.reasons[:5]
    reasons_text = "\n".join(f"• {reason}" for reason in reasons)

    return (
        f"🚨 СИГНАЛ\n\n"
        f"#{signal.symbol}\n"
        f"Направление: {signal.direction}\n"
        f"Вход: {_fmt_price(signal.entry_min)} - {_fmt_price(signal.entry_max)}\n"
        f"Stop: {_fmt_price(signal.stop_loss)}\n"
        f"TP1: {_fmt_price(signal.tp1)}\n"
        f"TP2: {_fmt_price(signal.tp2)}\n"
        f"TP3: {_fmt_price(signal.tp3)}\n"
        f"Score: {signal.score}/10\n\n"
        f"Причины:\n{reasons_text}"
    )


def format_result_message(item: dict) -> str:
    status = item["status"]
    symbol = item["symbol"]
    direction = item["direction"]
    realized_r = item.get("realized_r")

    icon = "✅"
    title = "Сделка закрыта в плюс"
    if status == "STOP_HIT":
        icon = "❌"
        title = "Сделка закрыта по стопу"
    elif status == "TP1_HIT":
        title = "Достигнут TP1"
    elif status == "TP2_HIT":
        title = "Достигнут TP2"
    elif status == "TP3_HIT":
        title = "Достигнут TP3"

    return (
        f"{icon} {title}\n\n"
        f"#{symbol}\n"
        f"Направление: {direction}\n"
        f"Статус: {status}\n"
        f"R результат: {realized_r}\n"
        f"Вход: {_fmt_price(float(item['entry_min']))} - {_fmt_price(float(item['entry_max']))}\n"
        f"Stop: {_fmt_price(float(item['stop_loss']))}\n"
        f"TP1: {_fmt_price(float(item['tp1']))}\n"
        f"TP2: {_fmt_price(float(item['tp2']))}\n"
        f"TP3: {_fmt_price(float(item['tp3']))}"
    )


async def send_text_to_all(bot: Bot, chat_ids: list[str], text: str):
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            continue


async def send_signal(bot: Bot, chat_ids: list[str], signal):
    await send_text_to_all(bot, chat_ids, format_signal(signal))