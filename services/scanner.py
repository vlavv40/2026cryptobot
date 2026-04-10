import asyncio
from datetime import datetime
from typing import List

from aiogram import Bot

from config import Config
from services.market_data import BinanceFuturesClient
from services.signal_engine import SignalCheckResult, SignalEngine, Signal
from services.state_store import StateStore
from services.telegram_sender import send_signal
from utils.logger import setup_logger

logger = setup_logger()


class MarketScanner:
    def __init__(self):
        self.client = BinanceFuturesClient()
        self.engine = SignalEngine()
        self.state = StateStore(Config.STATE_FILE)
        self._scan_lock = asyncio.Lock()

    def _make_cooldown_key(self, symbol: str, direction: str) -> str:
        return f"{symbol}:{direction}"

    def _make_signal_key(self, symbol: str, direction: str) -> str:
        return f"{symbol}:{direction}"

    def _is_on_cooldown(self, symbol: str, direction: str) -> bool:
        key = self._make_cooldown_key(symbol, direction)
        return self.state.get_cooldown(key) is not None

    def _set_cooldown(self, symbol: str, direction: str):
        key = self._make_cooldown_key(symbol, direction)
        self.state.set_cooldown(key, Config.SIGNAL_COOLDOWN_MINUTES)

    def _same_setup(self, signal: Signal) -> bool:
        key = self._make_signal_key(signal.symbol, signal.direction)
        previous = self.state.get_last_signal(key)

        if not previous:
            return False

        try:
            old_entry_mid = (float(previous["entry_min"]) + float(previous["entry_max"])) / 2
            new_entry_mid = (signal.entry_min + signal.entry_max) / 2

            old_sl = float(previous["stop_loss"])
            new_sl = signal.stop_loss

            old_tp1 = float(previous["tp1"])
            new_tp1 = signal.tp1

            def close_enough(old: float, new: float) -> bool:
                if old == 0:
                    return False
                return abs(new - old) / abs(old) <= Config.SETUP_PRICE_TOLERANCE

            return (
                close_enough(old_entry_mid, new_entry_mid)
                and close_enough(old_sl, new_sl)
                and close_enough(old_tp1, new_tp1)
            )
        except Exception:
            return False

    def _remember_signal(self, signal: Signal):
        key = self._make_signal_key(signal.symbol, signal.direction)
        payload = {
            "symbol": signal.symbol,
            "direction": signal.direction,
            "entry_min": signal.entry_min,
            "entry_max": signal.entry_max,
            "stop_loss": signal.stop_loss,
            "tp1": signal.tp1,
            "tp2": signal.tp2,
            "tp3": signal.tp3,
            "score": signal.score,
            "saved_at": datetime.utcnow().isoformat(),
        }
        self.state.set_last_signal(key, payload)

    def _format_diag(self, diagnostics: dict) -> str:
        if not diagnostics:
            return ""

        parts = []

        def add(name: str, key: str):
            value = diagnostics.get(key)
            if value is not None:
                parts.append(f"{name}={value}")

        add("ADX4h", "htf_adx")
        add("ADX1h", "mtf_adx")
        add("RSI15m", "ltf_rsi")
        add("MACD15m", "ltf_macd_hist")
        add("ATRr15m", "ltf_atr_ratio")
        add("Vol15m", "ltf_quote_volume_ratio")
        add("RR", "rr")
        add("ResGap", "resistance_gap")
        add("SupGap", "support_gap")

        return " | " + ", ".join(parts) if parts else ""

    async def _load_symbols_for_scan(self) -> list[str]:
        try:
            symbols = await self.client.get_liquid_symbols()
            if symbols:
                logger.info(f"После фильтра ликвидности выбрано пар: {len(symbols)}")
                return symbols
        except Exception as error:
            logger.exception(f"Не удалось загрузить ликвидные пары: {error}")

        logger.info("Использую резервный список пар из config.py")
        return Config.DEFAULT_SYMBOLS

    async def scan_market(self, bot: Bot, send_to_telegram: bool = True) -> List[SignalCheckResult]:
        async with self._scan_lock:
            logger.info(f"Старт сканирования рынка... режим={Config.STRATEGY_MODE}")

            symbols = await self._load_symbols_for_scan()
            results: List[SignalCheckResult] = []

            for symbol in symbols:
                try:
                    logger.info(f"Проверяю {symbol}")

                    htf_df = await self.client.get_klines(symbol, Config.HTF_INTERVAL, Config.KLINES_LIMIT)
                    mtf_df = await self.client.get_klines(symbol, Config.MTF_INTERVAL, Config.KLINES_LIMIT)
                    ltf_df = await self.client.get_klines(symbol, Config.LTF_INTERVAL, Config.KLINES_LIMIT)

                    result = self.engine.analyze_symbol(symbol, htf_df, mtf_df, ltf_df)
                    results.append(result)

                    if result.signal:
                        logger.info(
                            f"[SIGNAL] {symbol} {result.signal.direction} | "
                            f"score={result.signal.score}"
                            f"{self._format_diag(result.signal.diagnostics)}"
                        )
                    else:
                        logger.info(
                            f"[SKIP] {symbol} | Причина: {result.skip_reason}"
                            f"{self._format_diag(result.diagnostics)}"
                        )

                except Exception as error:
                    logger.exception(f"[ERROR] Ошибка при анализе {symbol}: {error}")

            good_signals = [r.signal for r in results if r.signal is not None]
            good_signals.sort(key=lambda s: s.score, reverse=True)

            final_signals = []
            for signal in good_signals:
                if self._is_on_cooldown(signal.symbol, signal.direction):
                    logger.info(f"[COOLDOWN] {signal.symbol} {signal.direction} | повторный сигнал пропущен")
                    continue

                if self._same_setup(signal):
                    logger.info(f"[DUPLICATE] {signal.symbol} {signal.direction} | тот же сетап, пропускаю")
                    continue

                final_signals.append(signal)

            top_signals = final_signals[: Config.MAX_SIGNALS_PER_SCAN]

            if not top_signals:
                logger.info("Сильных новых сигналов не найдено.")
                return results

            if send_to_telegram:
                for signal in top_signals:
                    try:
                        await send_signal(bot, Config.CHAT_ID, signal)
                        self._set_cooldown(signal.symbol, signal.direction)
                        self._remember_signal(signal)
                        logger.info(f"Сигнал отправлен: {signal.symbol}")
                    except Exception as error:
                        logger.exception(f"Ошибка отправки сигнала {signal.symbol}: {error}")

            return results