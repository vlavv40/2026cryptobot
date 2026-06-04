from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Сводка"),
                KeyboardButton(text="📈 Позиции"),
            ],
            [
                KeyboardButton(text="💵 Финансы"),
                KeyboardButton(text="🛡 Риск"),
            ],
            [
                KeyboardButton(text="📜 Журнал"),
                KeyboardButton(text="⚙️ Система"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери раздел",
    )


def get_stats_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Сводка"),
                KeyboardButton(text="💵 Финансы"),
            ],
            [
                KeyboardButton(text="🛡 Риск"),
                KeyboardButton(text="🪙 Статистика монет"),
            ],
            [
                KeyboardButton(text="↕️ LONG / SHORT"),
                KeyboardButton(text="📉 Кривая доходности"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Статистика",
    )


def get_trades_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📈 Позиции"),
                KeyboardButton(text="🧾 Ордера"),
            ],
            [
                KeyboardButton(text="📜 Журнал"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Сделки",
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
                KeyboardButton(text="🔄 Обновить список монет"),
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
