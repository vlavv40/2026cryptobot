import numpy as np
import pandas as pd


def add_ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    return df[column].ewm(span=period, adjust=False).mean()


def add_rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.Series:
    delta = df[column].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def add_macd(df: pd.DataFrame, column: str = "close"):
    ema12 = df[column].ewm(span=12, adjust=False).mean()
    ema26 = df[column].ewm(span=26, adjust=False).mean()

    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    return atr


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan))

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    return adx.fillna(0)


def atr_ratio(df: pd.DataFrame, atr_period: int = 14) -> pd.Series:
    atr = add_atr(df, atr_period)
    ratio = atr / df["close"].replace(0, np.nan)
    return ratio.fillna(0)


def add_support_resistance(df: pd.DataFrame, lookback: int = 30, swing_window: int = 2):
    """
    Более умные уровни:
    - ищем swing highs / swing lows
    - для каждой свечи берём последний актуальный уровень слева
    - не заглядываем в будущее
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    swing_highs = [np.nan] * n
    swing_lows = [np.nan] * n

    for i in range(swing_window, n - swing_window):
        current_high = highs[i]
        left_highs = highs[i - swing_window:i]
        right_highs = highs[i + 1:i + 1 + swing_window]

        current_low = lows[i]
        left_lows = lows[i - swing_window:i]
        right_lows = lows[i + 1:i + 1 + swing_window]

        if current_high > max(left_highs) and current_high >= max(right_highs):
            swing_highs[i] = current_high

        if current_low < min(left_lows) and current_low <= min(right_lows):
            swing_lows[i] = current_low

    resistance = []
    support = []

    for i in range(n):
        start = max(0, i - lookback)

        recent_swing_highs = [x for x in swing_highs[start:i] if not np.isnan(x)]
        recent_swing_lows = [x for x in swing_lows[start:i] if not np.isnan(x)]

        resistance.append(recent_swing_highs[-1] if recent_swing_highs else np.nan)
        support.append(recent_swing_lows[-1] if recent_swing_lows else np.nan)

    return pd.Series(support, index=df.index), pd.Series(resistance, index=df.index)