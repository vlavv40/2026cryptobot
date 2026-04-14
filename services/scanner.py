import asyncio
from collections import Counter
from datetime import datetime
from typing import List
from uuid import uuid4

from aiogram import Bot

from config import Config
from services.market_data import BinanceFuturesClient
from services.news_guard import NewsGuard
from services.paper_trader import PaperTrader
from services.signal_engine import SignalCheckResult, SignalEngine, Signal
from services.signal_log_store import SignalLogStore
from services.state_store import StateStore
from services.telegram_sender import (
    format_result_message,
    send_signal,
    send_text_to_all,
)
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
        self.paper = PaperTrader(start_balance=10000.0, risk_per_trade=0.01)
        self._scan_lock = asyncio.Lock()

        self.last_cycle_info = {
            "started_at": None,
            "finished_at": None,
            "symbols_checked": 0,
            "signals_found": 0,
            "news_block": False,
            "news_reason": "unknown",
            "sentiment": "NEUTRAL",
            "skip_summary": {},
            "top_signal_symbols": [],
        }

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
            "signal_type": getattr(signal, "signal_type", "UNKNOWN"),
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
            "signal_type": getattr(signal, "signal_type", "UNKNOWN"),
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

    def get_heartbeat(self) -> dict:
        return {
            "mode": Config.STRATEGY_MODE,
            "scan_interval": Config.SCAN_INTERVAL_SECONDS,
            "open_signals": len(self.get_open_signals()),
            "last_cycle": self.last_cycle_info,
            "paper_stats": self.paper.stats(),
        }

    async def _send_closed_signal_notifications(self, bot: Bot):
        items = self.trade_tracker.get_unnotified_closed_signals()

        for item in items:
            try:
                text = format_result_message(item)
                await send_text_to_all(bot, Config.CHAT_IDS, text)
                self.trade_tracker.mark_notified(item["id"])
                logger.info(f"[NOTIFY] Отправлен результат сигнала {item['symbol']} -> {item['status']}")
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
        add("Setup", "setup_type")

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

    def _log_paper_stats(self):
        stats = self.paper.stats()
        logger.info(
            "[PAPER STATS] "
            f"balance={stats['balance']}$ | "
            f"pnl={stats['pnl_usdt']}$ | "
            f"R={stats['total_r']} | "
            f"trades={stats['total_trades']} | "
            f"open={stats['open_trades']} | "
            f"closed={stats['closed_trades']} | "
            f"wins={stats['wins']} | "
            f"losses={stats['losses']} | "
            f"winrate={stats['winrate']}%"
        )

    async def _update_paper_trades_from_symbol(self, symbol: str):
        try:
            ltf_df = await self.client.get_klines(symbol, Config.LTF_INTERVAL, 5)
            if len(ltf_df) < 2:
                return

            last_closed = ltf_df.iloc[-2]
            high = float(last_closed["high"])
            low = float(last_closed["low"])

            closed_now = self.paper.update_symbol_price(symbol, high, low)

            for trade in closed_now:
                logger.info(
                    f"[PAPER CLOSED] {trade.symbol} {trade.direction} {trade.close_reason} | "
                    f"type={trade.signal_type} | result={trade.result_usdt}$ | R={trade.result_r}"
                )

        except Exception as error:
            logger.exception(f"[PAPER UPDATE ERROR] {symbol} | {error}")

    async def scan_market(self, bot: Bot, send_to_telegram: bool = True) -> List[SignalCheckResult]:
        async with self._scan_lock:
            await self.check_open_signals(bot)

            cycle_started_at = datetime.utcnow().isoformat()
            news_decision = await self.news_guard.evaluate_market()

            logger.info(
                f"Старт сканирования рынка... режим={Config.STRATEGY_MODE} | "
                f"news_block={news_decision.blocked} | "
                f"sentiment={news_decision.sentiment_bias} | "
                f"news_reason={news_decision.reason}"
            )

            if news_decision.blocked:
                self.last_cycle_info = {
                    "started_at": cycle_started_at,
                    "finished_at": datetime.utcnow().isoformat(),
                    "symbols_checked": 0,
                    "signals_found": 0,
                    "news_block": True,
                    "news_reason": news_decision.reason,
                    "sentiment": news_decision.sentiment_bias,
                    "skip_summary": {"news block": 1},
                    "top_signal_symbols": [],
                }

                if send_to_telegram and Config.SEND_NEWS_BLOCK_MESSAGE:
                    await send_text_to_all(
                        bot,
                        Config.CHAT_IDS,
                        f"🛑 News block\n\nПричина: {news_decision.reason}\nSentiment: {news_decision.sentiment_bias}",
                    )

                logger.info(f"[NEWS BLOCK] {news_decision.reason}")
                self._log_paper_stats()
                return []

            symbols = await self._load_symbols_for_scan()

            if send_to_telegram and Config.SEND_CYCLE_MESSAGES:
                await send_text_to_all(
                    bot,
                    Config.CHAT_IDS,
                    (
                        "🔄 Новый цикл анализа\n\n"
                        f"Режим: {Config.STRATEGY_MODE}\n"
                        f"Пары в анализе: {len(symbols)}\n"
                        f"Sentiment: {news_decision.sentiment_bias}\n"
                        f"Открытых сигналов: {len(self.get_open_signals())}"
                    ),
                )

            results: List[SignalCheckResult] = []
            skip_counter = Counter()

            for symbol in symbols:
                try:
                    await self._update_paper_trades_from_symbol(symbol)

                    logger.info(f"Проверяю {symbol}")

                    htf_df = await self.client.get_klines(symbol, Config.HTF_INTERVAL, Config.KLINES_LIMIT)
                    mtf_df = await self.client.get_klines(symbol, Config.MTF_INTERVAL, Config.KLINES_LIMIT)
                    ltf_df = await self.client.get_klines(symbol, Config.LTF_INTERVAL, Config.KLINES_LIMIT)

                    result = self.engine.analyze_symbol(symbol, htf_df, mtf_df, ltf_df)

                    if result.signal:
                        if news_decision.sentiment_bias == "BEARISH" and result.signal.direction == "LONG":
                            result.signal.score = round(result.signal.score - 0.7, 1)
                            result.signal.reasons.append("news guard: bearish headlines reduce LONG confidence")

                        if news_decision.sentiment_bias == "BULLISH" and result.signal.direction == "SHORT":
                            result.signal.score = round(result.signal.score - 0.7, 1)
                            result.signal.reasons.append("news guard: bullish headlines reduce SHORT confidence")

                    results.append(result)

                    if result.signal:
                        logger.info(
                            f"[SIGNAL] {symbol} {result.signal.direction} {result.signal.signal_type} | "
                            f"score={result.signal.score}"
                            f"{self._format_diag(result.signal.diagnostics)}"
                        )
                    else:
                        skip_counter[result.skip_reason] += 1
                        logger.info(
                            f"[SKIP] {symbol} | Причина: {result.skip_reason}"
                            f"{self._format_diag(result.diagnostics)}"
                        )

                except Exception as error:
                    logger.exception(f"[ERROR] Ошибка при анализе {symbol}: {error}")
                    skip_counter["internal analysis error"] += 1

            good_signals = [r.signal for r in results if r.signal is not None]
            good_signals.sort(
                key=lambda s: (
                    1 if getattr(s, "signal_type", "SETUP") == "STRONG" else 0,
                    s.score,
                ),
                reverse=True,
            )

            final_signals = []
            for signal in good_signals:
                if self._is_on_cooldown(signal.symbol, signal.direction):
                    logger.info(f"[COOLDOWN] {signal.symbol} {signal.direction} | повторный сигнал пропущен")
                    skip_counter["cooldown"] += 1
                    continue

                if self._same_setup(signal):
                    logger.info(f"[DUPLICATE] {signal.symbol} {signal.direction} | тот же сетап, пропускаю")
                    skip_counter["duplicate setup"] += 1
                    continue

                final_signals.append(signal)

            top_signals = final_signals[: Config.MAX_SIGNALS_PER_SCAN]

            if send_to_telegram and top_signals:
                for signal in top_signals:
                    try:
                        await send_signal(bot, Config.CHAT_IDS, signal)
                        self._set_cooldown(signal.symbol, signal.direction)
                        self._remember_signal(signal)
                        self._log_signal_to_history(signal)
                        self._track_new_signal(signal)

                        paper_trade = self.paper.open_trade(signal)
                        if paper_trade:
                            logger.info(
                                f"[PAPER OPEN] {paper_trade.symbol} {paper_trade.direction} {paper_trade.signal_type} | "
                                f"entry={round(paper_trade.entry_price, 6)} | "
                                f"risk={round(paper_trade.risk_amount, 2)}$ | "
                                f"size={round(paper_trade.size, 2)}"
                            )

                        logger.info(f"Сигнал отправлен: {signal.symbol}")
                    except Exception as error:
                        logger.exception(f"Ошибка отправки сигнала {signal.symbol}: {error}")

            self.last_cycle_info = {
                "started_at": cycle_started_at,
                "finished_at": datetime.utcnow().isoformat(),
                "symbols_checked": len(symbols),
                "signals_found": len(top_signals),
                "news_block": False,
                "news_reason": news_decision.reason,
                "sentiment": news_decision.sentiment_bias,
                "skip_summary": dict(skip_counter),
                "top_signal_symbols": [s.symbol for s in top_signals],
            }

            if send_to_telegram and Config.SEND_CYCLE_MESSAGES:
                if skip_counter:
                    top_reasons = sorted(skip_counter.items(), key=lambda x: x[1], reverse=True)[:5]
                    reasons_text = "\n".join(f"• {reason}: {count}" for reason, count in top_reasons)
                else:
                    reasons_text = "• нет skip-причин"

                await send_text_to_all(
                    bot,
                    Config.CHAT_IDS,
                    (
                        "✅ Цикл завершён\n\n"
                        f"Проверено пар: {len(symbols)}\n"
                        f"Найдено сильных сигналов: {len(top_signals)}\n"
                        f"Главные причины skip:\n{reasons_text}"
                    ),
                )

            if not top_signals:
                logger.info("Сильных новых сигналов не найдено.")

            self._log_paper_stats()
            return results