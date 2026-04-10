from aiogram import Bot
from services.signal_engine import Signal


def format_signal_message(signal: Signal) -> str:
    reasons_text = "\n".join([f"- {reason}" for reason in signal.reasons])

    return (
        f"🌟 {signal.symbol}\n"
        f"🕯 Направление: {signal.direction}\n"
        f"💲 Вход: {signal.entry_min} - {signal.entry_max}\n"
        f"🛑 Stop Loss: {signal.stop_loss}\n"
        f"🎯 TP1: {signal.tp1}\n"
        f"🎯 TP2: {signal.tp2}\n"
        f"🎯 TP3: {signal.tp3}\n"
        f"📊 Сила сигнала: {signal.score}/10\n"
        f"🧠 Причина:\n"
        f"{reasons_text}"
    )


async def send_signal(bot: Bot, chat_id: str, signal: Signal):
    text = format_signal_message(signal)
    await bot.send_message(chat_id=chat_id, text=text)