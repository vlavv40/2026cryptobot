from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🟢 Система"),
                KeyboardButton(text="📈 Статистика"),
            ],
            [
                KeyboardButton(text="💼 Сделки"),
                KeyboardButton(text="🪙 Монеты"),
            ],
            [
                KeyboardButton(text="📤 Экспорт"),
                KeyboardButton(text="⚙️ Админ"),
            ],
            [
                KeyboardButton(text="📌 Сигналы"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие 👇",
    )


def get_stats_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Общая статистика"),
                KeyboardButton(text="🪙 Статистика монет"),
            ],
            [
                KeyboardButton(text="↕️ LONG / SHORT"),
                KeyboardButton(text="📉 Equity Curve"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Статистика 👇",
    )


def get_trades_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📂 Открытые"),
                KeyboardButton(text="🧾 Ордера"),
            ],
            [
                KeyboardButton(text="📜 История"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Раздел сделок 👇",
    )


def get_export_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📄 CSV"),
                KeyboardButton(text="📊 Excel"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Экспорт 👇",
    )


def get_admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🏷 Версия"),
                KeyboardButton(text="🔄 Обновить WhiteList"),
            ],
            [
                KeyboardButton(text="♻️ Сброс статистики"),
                KeyboardButton(text="🧹 Сброс базы"),
            ],
            [
                KeyboardButton(text="🔁 Перезапуск"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Админ 👇",
    )


def get_reset_db_confirm_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="✅ Подтвердить сброс базы"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Подтверждение 👇",
    )
