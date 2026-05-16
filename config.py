import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # =========================================================
    # BASIC
    # =========================================================
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

    RAW_CHAT_IDS = os.getenv("CHAT_IDS", "")
    CHAT_IDS = [chat_id.strip() for chat_id in RAW_CHAT_IDS.split(",") if chat_id.strip()]

    POSTGRES_URI = os.getenv("POSTGRES_URI", "")
    CRYPTO_PULSE_URL = os.getenv("CRYPTO_PULSE_URL", "")
    BOT_INGEST_SECRET = os.getenv("BOT_INGEST_SECRET", "")

    BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"
    PROXY_URL = os.getenv("PROXY_URL", "")
    # =========================================================
    # MODE
    # =========================================================
    STRATEGY_MODE = os.getenv("STRATEGY_MODE", "BALANCED_PRO").upper()

    # =========================================================
    # TIMEFRAMES
    # =========================================================
    HTF_INTERVAL = "4h"
    MTF_INTERVAL = "1h"
    LTF_INTERVAL = "15m"

    KLINES_LIMIT = 260

    # =========================================================
    # SCANNER
    # =========================================================
    SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
    MAX_SIGNALS_PER_SCAN = int(os.getenv("MAX_SIGNALS_PER_SCAN", "5"))

    USE_PRIORITY_SYMBOLS_ONLY = os.getenv("USE_PRIORITY_SYMBOLS_ONLY", "false").lower() == "true"
    MAX_SYMBOLS_TO_SCAN = int(os.getenv("MAX_SYMBOLS_TO_SCAN", "100"))

    PRIORITY_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
        "DOTUSDT", "NEARUSDT", "ARBUSDT", "OPUSDT", "ATOMUSDT",
    ]
    DEFAULT_SYMBOLS = PRIORITY_SYMBOLS.copy()

    # =========================================================
    # INDICATORS
    # =========================================================
    EMA_ENTRY_FAST = 20
    EMA_ENTRY_SLOW = 50
    EMA_FAST = 50
    EMA_SLOW = 200
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    ADX_PERIOD = 14

    # =========================================================
    # MARKET / LIQUIDITY
    # =========================================================
    MIN_24H_QUOTE_VOLUME = float(os.getenv("MIN_24H_QUOTE_VOLUME", "30000000"))
    MIN_24H_TRADES = int(os.getenv("MIN_24H_TRADES", "30000"))

    SIGNAL_COOLDOWN_MINUTES = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "180"))
    SETUP_PRICE_TOLERANCE = float(os.getenv("SETUP_PRICE_TOLERANCE", "0.0035"))

    # =========================================================
    # NEWS
    # =========================================================
    NEWS_GUARD_ENABLED = os.getenv("NEWS_GUARD_ENABLED", "false").lower() == "true"
    NEWS_SENTIMENT_ENABLED = os.getenv("NEWS_SENTIMENT_ENABLED", "false").lower() == "true"

    FMP_API_KEY = os.getenv("FMP_API_KEY", "")
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

    NEWS_LOOKAHEAD_MINUTES = int(os.getenv("NEWS_LOOKAHEAD_MINUTES", "60"))
    NEWS_COOLDOWN_AFTER_MINUTES = int(os.getenv("NEWS_COOLDOWN_AFTER_MINUTES", "30"))
    BLOCK_HIGH_IMPACT_NEWS_ONLY = os.getenv("BLOCK_HIGH_IMPACT_NEWS_ONLY", "true").lower() == "true"
    NEWS_SENTIMENT_BLOCK_THRESHOLD = int(os.getenv("NEWS_SENTIMENT_BLOCK_THRESHOLD", "2"))

    # =========================================================
    # TELEGRAM / MESSAGES
    # =========================================================
    SEND_STARTUP_MESSAGE = os.getenv("SEND_STARTUP_MESSAGE", "true").lower() == "true"
    SEND_CYCLE_MESSAGES = os.getenv("SEND_CYCLE_MESSAGES", "false").lower() == "true"
    SEND_NEWS_BLOCK_MESSAGE = os.getenv("SEND_NEWS_BLOCK_MESSAGE", "true").lower() == "true"

    # =========================================================
    # ENTRY / RSI FILTERS
    # =========================================================
    LONG_MAX_RSI_ENTRY = float(os.getenv("LONG_MAX_RSI_ENTRY", "70"))
    SHORT_MIN_RSI_ENTRY = float(os.getenv("SHORT_MIN_RSI_ENTRY", "30"))

    MAX_CHASE_DISTANCE_FROM_EMA20 = float(os.getenv("MAX_CHASE_DISTANCE_FROM_EMA20", "0.022"))
    MAX_CHASE_DISTANCE_FROM_EMA50 = float(os.getenv("MAX_CHASE_DISTANCE_FROM_EMA50", "0.035"))

    MIN_STOP_BUFFER_ATR = float(os.getenv("MIN_STOP_BUFFER_ATR", "0.28"))

    HARD_MIN_RESISTANCE_GAP = float(os.getenv("HARD_MIN_RESISTANCE_GAP", "0.0045"))
    HARD_MIN_SUPPORT_GAP = float(os.getenv("HARD_MIN_SUPPORT_GAP", "0.0045"))

    # =========================================================
    # SIGNAL CLASSIFICATION
    # =========================================================
    STRONG_MIN_SCORE = float(os.getenv("STRONG_MIN_SCORE", "6.6"))
    STRONG_MIN_RR = float(os.getenv("STRONG_MIN_RR", "1.15"))

    SETUP_MIN_SCORE = float(os.getenv("SETUP_MIN_SCORE", "5.9"))
    SETUP_MIN_RR = float(os.getenv("SETUP_MIN_RR", "1.05"))

    MIN_SCORE = STRONG_MIN_SCORE
    MIN_RR = STRONG_MIN_RR

    # =========================================================
    # STRATEGY MODE TUNING
    # =========================================================
    if STRATEGY_MODE == "SNIPER":
        MIN_ADX_4H = float(os.getenv("MIN_ADX_4H", "18.0"))
        MIN_ADX_1H = float(os.getenv("MIN_ADX_1H", "15.0"))
        MIN_ATR_RATIO_15M = float(os.getenv("MIN_ATR_RATIO_15M", "0.0038"))

        MAX_DISTANCE_FROM_EMA20 = float(os.getenv("MAX_DISTANCE_FROM_EMA20", "0.020"))
        MAX_DISTANCE_FROM_EMA50 = float(os.getenv("MAX_DISTANCE_FROM_EMA50", "0.030"))

        MIN_RESISTANCE_GAP = float(os.getenv("MIN_RESISTANCE_GAP", "0.006"))
        MIN_SUPPORT_GAP = float(os.getenv("MIN_SUPPORT_GAP", "0.006"))

        MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO = float(os.getenv("MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO", "0.78"))
    else:
        # BALANCED_PRO / default
        MIN_ADX_4H = float(os.getenv("MIN_ADX_4H", "15.0"))
        MIN_ADX_1H = float(os.getenv("MIN_ADX_1H", "15.0"))
        MIN_ATR_RATIO_15M = float(os.getenv("MIN_ATR_RATIO_15M", "0.0038"))

        MAX_DISTANCE_FROM_EMA20 = float(os.getenv("MAX_DISTANCE_FROM_EMA20", "0.022"))
        MAX_DISTANCE_FROM_EMA50 = float(os.getenv("MAX_DISTANCE_FROM_EMA50", "0.034"))

        MIN_RESISTANCE_GAP = float(os.getenv("MIN_RESISTANCE_GAP", "0.0045"))
        MIN_SUPPORT_GAP = float(os.getenv("MIN_SUPPORT_GAP", "0.0045"))

        MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO = float(os.getenv("MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO", "0.70"))

    # =========================================================
    # HARD FILTERS FOR ENTRY QUALITY
    # =========================================================
    MIN_CONFIRMATION_VOLUME_RATIO = float(os.getenv("MIN_CONFIRMATION_VOLUME_RATIO", "0.70"))
    MAX_ENTRY_BODY_ATR = float(os.getenv("MAX_ENTRY_BODY_ATR", "1.20"))
    MAX_BAD_WICK_RATIO = float(os.getenv("MAX_BAD_WICK_RATIO", "0.45"))

        # =========================================================
    # AUTO TRADE / BINANCE EXECUTION
    # =========================================================
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

    AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"
    AUTO_TRADE_USDT = float(os.getenv("AUTO_TRADE_USDT", "10"))
    AUTO_TRADE_LEVERAGE = int(os.getenv("AUTO_TRADE_LEVERAGE", "3"))
    AUTO_TRADE_MARGIN_TYPE = os.getenv("AUTO_TRADE_MARGIN_TYPE", "ISOLATED").upper()
    AUTO_TRADE_ONE_POSITION_PER_SYMBOL = os.getenv("AUTO_TRADE_ONE_POSITION_PER_SYMBOL", "true").lower() == "true"
