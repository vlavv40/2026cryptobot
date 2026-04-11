from aiogram import Bot


def format_signal(signal) -> str:
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
        f"🧠 Причина:\n{reasons_text}"
    )


async def send_text_to_all(bot: Bot, chat_ids: list[str], text: str):
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            # Не валим весь цикл, если одному пользователю не удалось отправить
            continue


async def send_signal(bot: Bot, chat_ids: list[str], signal):
    text = format_signal(signal)
    await send_text_to_all(bot, chat_ids, text)