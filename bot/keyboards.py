from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


main_menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📊 Статус"),
            KeyboardButton(text="💓 Пульс"),
        ],
        [
            KeyboardButton(text="🧪 Статистика paper"),
            KeyboardButton(text="📂 Открытые сделки"),
        ],
        [
            KeyboardButton(text="📜 История сделок"),
            KeyboardButton(text="📈 Статистика сигналов"),
        ],
        [
            KeyboardButton(text="🔄 Анализ рынка"),
            KeyboardButton(text="🧹 Сбросить paper"),
        ],
        [
            KeyboardButton(text="⚙️ Настройки"),
            KeyboardButton(text="📌 Последние сигналы"),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие 👇",
)