from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


main_menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📊 Статус"),
            KeyboardButton(text="💓 Heartbeat"),
        ],
        [
            KeyboardButton(text="🧪 Paper stats"),
            KeyboardButton(text="📂 Open paper"),
        ],
        [
            KeyboardButton(text="📜 Paper history"),
            KeyboardButton(text="📈 Signal stats"),
        ],
        [
            KeyboardButton(text="🔄 Scan now"),
            KeyboardButton(text="🧹 Reset paper"),
        ],
        [
            KeyboardButton(text="⚙️ Mode"),
            KeyboardButton(text="📌 Last signals"),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие",
)