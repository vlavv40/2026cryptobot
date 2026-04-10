import asyncio
from datetime import datetime
from typing import List
from uuid import uuid4

from aiogram import Bot

from config import Config
from services.market_data import BinanceFuturesClient
from services.news_guard import NewsGuard
from services.signal_engine import SignalCheckResult, SignalEngine, Signal
from services.signal_log_store import SignalLogStore
from services.state_store import StateStore
from services.telegram_sender import send_signal
from services.trade_tracker import TradeTracker
from utils.logger import setup_logger

logger = setup_logger()


class MarketScanner:
    def __init__(self):
        self.client = BinanceFuturesClient()
        self.engine = SignalEngine()
        self.news_guard = NewsGuard()
        self.state = StateStore(Config.STATE_FILE)
        self.signal_log = SignalLogStore()
        self.trade_tracker = TradeTracker()
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

    def _log_signal_to_history(self, signal: Signal):
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
            "reasons": signal.reasons,
            "diagnostics": signal.diagnostics,
        }
        self.signal_log.add_signal(payload)

    def _track_new_signal(self, signal: Signal):
        payload = {
            "id": str(uuid4()),
            "symbol": signal.symbol,
            "direction": signal.direction,
            "entry_min": signal.entry_min,
            "entry_max": signal.entry_max,
            "stop_loss": signal.stop_loss,
            "tp1": signal.tp1,
            "tp2": signal.tp2,
            "tp3": signal.tp3,
            "score": signal.score,
        }
        self.trade_tracker.add_signal(payload)

    def get_last_logged_signals(self, limit: int = 5) -> list[dict]:
        return self.signal_log.get_last_signals(limit=limit)

    def get_open_signals(self) -> list[dict]:
        return self.trade_tracker.get_open_signals()

    def get_stats(self) -> dict:
        return self.trade_tracker.get_stats()

    def get_pair_stats(self) -> list[dict]:
        return self.trade_tracker.get_pair_stats()

    def get_best_pairs(self, min_closed: int = 1, limit: int = 5) -> list[dict]:
        return self.trade_tracker.get_best_pairs(min_closed=min_closed, limit=limit)

    def get_side_stats(self) -> dict:
        return self.trade_tracker.get_side_stats()

    def get_daily_report(self) -> list[dict]:
        return self.trade_tracker.get_daily_report()

    def get_weekly_report(self) -> list[dict]:
        return self.trade_tracker.get_weekly_report()

    def get_csv_path(self) -> str:
        return self.trade_tracker.get_csv_path()

    def get_json_path(self) -> str:
        return self.trade_tracker.get_json_path()

    async def get_news_guard_status(self) -> dict:
        decision = await self.news_guard.evaluate_market()
        return {
            "blocked": decision.blocked,
            "reason": decision.reason,
            "sentiment_bias": decision.sentiment_bias,
            "negative_count": decision.negative_count,
            "positive_count": decision.positive_count,
            "macro_events_count": len(decision.macro_events),
        }

    async def _send_closed_signal_notifications(self, bot: Bot):
        items = self.trade_tracker.get_unnotified_closed_signals()

        for item in items:
            try:
                status = item["status"]
                symbol = item["symbol"]
                direction = item["direction"]
                realized_r = item.get("realized_r")

                emoji_map = {
                    "TP1_HIT": "✅",
                    "TP2_HIT": "✅",
                    "TP3_HIT": "✅",
                    "STOP_HIT": "❌",
                }

                emoji = emoji_map.get(status, "ℹ️")

                text = (
                    f"{emoji} Результат сигнала\n\n"
                    f"Монета: {symbol}\n"
                    f"Направление: {direction}\n"
                    f"Статус: {status}\n"
                    f"R результат: {realized_r}\n"
                    f"Вход: {item['entry_min']} - {item['entry_max']}\n"
                    f"Stop Loss: {item['stop_loss']}\n"
                    f"TP1: {item['tp1']}\n"
                    f"TP2: {item['tp2']}\n"
                    f"TP3: {item['tp3']}"
                )

                await bot.send_message(chat_id=Config.CHAT_ID, text=text)
                self.trade_tracker.mark_notified(item["id"])
                logger.info(f"[NOTIFY] Отправлен результат сигнала {symbol} -> {status}")

            except Exception as error:
                logger.exception(f"[NOTIFY ERROR] {item.get('symbol')} | {error}")

    async def check_open_signals(self, bot: Bot):
        open_signals = self.trade_tracker.get_open_signals()

        if open_signals:
            for item in open_signals:
                try:
                    symbol = item["symbol"]
                    direction = item["direction"]

                    ltf_df = await self.client.get_klines(symbol, Config.LTF_INTERVAL, 5)
                    if len(ltf_df) < 2:
                        continue

                    last_closed = ltf_df.iloc[-2]
                    high = float(last_closed["high"])
                    low = float(last_closed["low"])

                    stop_loss = float(item["stop_loss"])
                    tp1 = float(item["tp1"])
                    tp2 = float(item["tp2"])
                    tp3 = float(item["tp3"])

                    new_status = None

                    if direction == "LONG":
                        if low <= stop_loss:
                            new_status = "STOP_HIT"
                        elif high >= tp3:
                            new_status = "TP3_HIT"
                        elif high >= tp2:
                            new_status = "TP2_HIT"
                        elif high >= tp1:
                            new_status = "TP1_HIT"
                    else:
                        if high >= stop_loss:
                            new_status = "STOP_HIT"
                        elif low <= tp3:
                            new_status = "TP3_HIT"
                        elif low <= tp2:
                            new_status = "TP2_HIT"
                        elif low <= tp1:
                            new_status = "TP1_HIT"

                    if new_status:
                        self.trade_tracker.update_signal(item["id"], new_status)
                        logger.info(f"[TRACKER] {symbol} {direction} -> {new_status}")

                except Exception as error:
                    logger.exception(f"[TRACKER ERROR] {item.get('symbol')} | {error}")

        await self._send_closed_signal_notifications(bot)

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
            await self.check_open_signals(bot)

            news_decision = await self.news_guard.evaluate_market()
            logger.info(
                f"Старт сканирования рынка... режим={Config.STRATEGY_MODE} | "
                f"news_block={news_decision.blocked} | "
                f"sentiment={news_decision.sentiment_bias} | "
                f"news_reason={news_decision.reason}"
            )

            if news_decision.blocked:
                logger.info(f"[NEWS BLOCK] {news_decision.reason}")
                return []

            symbols = await self._load_symbols_for_scan()
            results: List[SignalCheckResult] = []

            for symbol in symbols:
                try:
                    logger.info(f"Проверяю {symbol}")

                    htf_df = await self.client.get_klines(symbol, Config.HTF_INTERVAL, Config.KLINES_LIMIT)
                    mtf_df = await self.client.get_klines(symbol, Config.MTF_INTERVAL, Config.KLINES_LIMIT)
                    ltf_df = await self.client.get_klines(symbol, Config.LTF_INTERVAL, Config.KLINES_LIMIT)

                    result = self.engine.analyze_symbol(symbol, htf_df, mtf_df, ltf_df)

                    if result.signal:
                        if news_decision.sentiment_bias == "BEARISH" and result.signal.direction == "LONG":
                            result.signal.score = round(result.signal.score - 0.7, 1)
                            result.signal.reasons.append(
                                "news guard: bearish headlines reduce LONG confidence"
                            )

                        if news_decision.sentiment_bias == "BULLISH" and result.signal.direction == "SHORT":
                            result.signal.score = round(result.signal.score - 0.7, 1)
                            result.signal.reasons.append(
                                "news guard: bullish headlines reduce SHORT confidence"
                            )

                        if result.signal.score < Config.MIN_SCORE:
                            result = SignalCheckResult(
                                symbol=result.symbol,
                                signal=None,
                                skip_reason="news guard lowered score below threshold",
                                diagnostics=result.diagnostics,
                            )

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
                    logger.exception(f"[SCAN ERROR] {symbol} | {error}")

            if send_to_telegram:
                for result in results:
                    if not result.signal:
                        continue

                    signal = result.signal

                    try:
                        if self._is_on_cooldown(signal.symbol, signal.direction):
                            logger.info(f"[COOLDOWN] {signal.symbol} {signal.direction}")
                            continue

                        if self._same_setup(signal):
                            logger.info(f"[DUPLICATE] {signal.symbol} {signal.direction}")
                            continue

                        await send_signal(bot, signal)
                        self._set_cooldown(signal.symbol, signal.direction)
                        self._remember_signal(signal)
                        self._log_signal_to_history(signal)
                        self._track_new_signal(signal)

                        logger.info(
                            f"[SENT] {signal.symbol} {signal.direction} | score={signal.score}"
                        )

                    except Exception as error:
                        logger.exception(
                            f"[SEND ERROR] {signal.symbol} {signal.direction} | {error}"
                        )

            return results