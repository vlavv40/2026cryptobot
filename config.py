import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

    RAW_CHAT_IDS = os.getenv("CHAT_IDS", "")
    CHAT_IDS = [chat_id.strip() for chat_id in RAW_CHAT_IDS.split(",") if chat_id.strip()]

    POSTGRES_URI = os.getenv("POSTGRES_URI", "")

    BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"

    STRATEGY_MODE = os.getenv("STRATEGY_MODE", "BALANCED_PRO")

    HTF_INTERVAL = "4h"
    MTF_INTERVAL = "1h"
    LTF_INTERVAL = "15m"

    KLINES_LIMIT = 260

    SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
    MAX_SIGNALS_PER_SCAN = int(os.getenv("MAX_SIGNALS_PER_SCAN", "2"))

    USE_PRIORITY_SYMBOLS_ONLY = os.getenv("USE_PRIORITY_SYMBOLS_ONLY", "true").lower() == "true"
    MAX_SYMBOLS_TO_SCAN = int(os.getenv("MAX_SYMBOLS_TO_SCAN", "15"))

    PRIORITY_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
        "DOTUSDT", "NEARUSDT", "ARBUSDT", "OPUSDT", "ATOMUSDT",
    ]
    DEFAULT_SYMBOLS = PRIORITY_SYMBOLS.copy()

    EMA_ENTRY_FAST = 20
    EMA_ENTRY_SLOW = 50
    EMA_FAST = 50
    EMA_SLOW = 200
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    ADX_PERIOD = 14

    MIN_24H_QUOTE_VOLUME = 100_000_000
    MIN_24H_TRADES = 100_000

    SIGNAL_COOLDOWN_MINUTES = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "180"))
    SETUP_PRICE_TOLERANCE = 0.0035

    NEWS_GUARD_ENABLED = os.getenv("NEWS_GUARD_ENABLED", "false").lower() == "true"
    NEWS_SENTIMENT_ENABLED = os.getenv("NEWS_SENTIMENT_ENABLED", "false").lower() == "true"

    FMP_API_KEY = os.getenv("FMP_API_KEY", "")
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

    NEWS_LOOKAHEAD_MINUTES = int(os.getenv("NEWS_LOOKAHEAD_MINUTES", "60"))
    NEWS_COOLDOWN_AFTER_MINUTES = int(os.getenv("NEWS_COOLDOWN_AFTER_MINUTES", "30"))
    BLOCK_HIGH_IMPACT_NEWS_ONLY = os.getenv("BLOCK_HIGH_IMPACT_NEWS_ONLY", "true").lower() == "true"
    NEWS_SENTIMENT_BLOCK_THRESHOLD = int(os.getenv("NEWS_SENTIMENT_BLOCK_THRESHOLD", "2"))

    SEND_STARTUP_MESSAGE = os.getenv("SEND_STARTUP_MESSAGE", "true").lower() == "true"
    SEND_CYCLE_MESSAGES = os.getenv("SEND_CYCLE_MESSAGES", "false").lower() == "true"
    SEND_NEWS_BLOCK_MESSAGE = os.getenv("SEND_NEWS_BLOCK_MESSAGE", "true").lower() == "true"

    LONG_MAX_RSI_ENTRY = float(os.getenv("LONG_MAX_RSI_ENTRY", "62"))
    SHORT_MIN_RSI_ENTRY = float(os.getenv("SHORT_MIN_RSI_ENTRY", "38"))

    MAX_CHASE_DISTANCE_FROM_EMA20 = float(os.getenv("MAX_CHASE_DISTANCE_FROM_EMA20", "0.012"))
    MAX_CHASE_DISTANCE_FROM_EMA50 = float(os.getenv("MAX_CHASE_DISTANCE_FROM_EMA50", "0.020"))

    MIN_STOP_BUFFER_ATR = float(os.getenv("MIN_STOP_BUFFER_ATR", "0.15"))

    HARD_MIN_RESISTANCE_GAP = float(os.getenv("HARD_MIN_RESISTANCE_GAP", "0.010"))
    HARD_MIN_SUPPORT_GAP = float(os.getenv("HARD_MIN_SUPPORT_GAP", "0.010"))

    STRONG_MIN_SCORE = float(os.getenv("STRONG_MIN_SCORE", "8.2"))
    STRONG_MIN_RR = float(os.getenv("STRONG_MIN_RR", "1.8"))

    SETUP_MIN_SCORE = float(os.getenv("SETUP_MIN_SCORE", "6.8"))
    SETUP_MIN_RR = float(os.getenv("SETUP_MIN_RR", "1.6"))

    MIN_SCORE = STRONG_MIN_SCORE
    MIN_RR = STRONG_MIN_RR

    if STRATEGY_MODE == "SNIPER":
        MIN_ADX_4H = 20.0
        MIN_ADX_1H = 16.0
        MIN_ATR_RATIO_15M = 0.0018
        MAX_DISTANCE_FROM_EMA20 = 0.018
        MAX_DISTANCE_FROM_EMA50 = 0.028
        MIN_RESISTANCE_GAP = 0.010
        MIN_SUPPORT_GAP = 0.010
        MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO = 0.85
    else:
        MIN_ADX_4H = 22.0
        MIN_ADX_1H = 18.0
        MIN_ATR_RATIO_15M = 0.0018
        MAX_DISTANCE_FROM_EMA20 = 0.020
        MAX_DISTANCE_FROM_EMA50 = 0.030
        MIN_RESISTANCE_GAP = 0.008
        MIN_SUPPORT_GAP = 0.008
        MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO = 0.90

    # hard filters for entry quality
    MIN_CONFIRMATION_VOLUME_RATIO = float(os.getenv("MIN_CONFIRMATION_VOLUME_RATIO", "1.05"))
    MAX_ENTRY_BODY_ATR = float(os.getenv("MAX_ENTRY_BODY_ATR", "0.90"))
    MAX_BAD_WICK_RATIO = float(os.getenv("MAX_BAD_WICK_RATIO", "0.45"))
