from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статус"),
                KeyboardButton(text="💼 Сделки"),
            ],
            [
                KeyboardButton(text="📈 Статистика"),
                KeyboardButton(text="📌 Сигналы"),
            ],
            [
                KeyboardButton(text="🧹 Сброс"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие 👇",
    )


def get_trades_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📂 Открытые"),
                KeyboardButton(text="📜 История"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True,
    )