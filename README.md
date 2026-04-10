# Crypto Signal Bot

Telegram-бот для анализа Binance Futures USDT и отправки торговых сигналов.

## Возможности

- Анализ Binance Futures USDT
- Multi-timeframe логика: 4h / 1h / 15m
- EMA, RSI, MACD, ATR, ADX
- Фильтр по ликвидности
- Защита от дублей
- Cooldown по сигналам
- Логи причин skip
- Режимы:
  - `BALANCED_PRO`
  - `SNIPER`

## Структура проекта

```text
crypto_signal_bot/
├── main.py
├── config.py
├── requirements.txt
├── Procfile
├── README.md
├── .gitignore
├── .env
│
├── bot/
│   ├── __init__.py
│   └── handlers.py
│
├── services/
│   ├── __init__.py
│   ├── market_data.py
│   ├── indicators.py
│   ├── signal_engine.py
│   ├── scanner.py
│   ├── telegram_sender.py
│   └── state_store.py
│
└── utils/
    ├── __init__.py
    └── logger.py