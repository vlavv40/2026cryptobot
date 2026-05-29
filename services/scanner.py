import asyncio
from collections import Counter
from datetime import datetime
from typing import List
from uuid import uuid4

from aiogram import Bot

from config import Config
from services.btc_filter import BTCFilter
from services.market_data import BinanceFuturesClient
from services.news_guard import NewsGuard
from services.paper_trader import PaperTrader
from services.signal_engine import SignalCheckResult, SignalEngine, Signal
from services.signal_log_store import SignalLogStore
from services.state_store import StateStore
from services.telegram_sender import (
    format_result_message,
    format_trade_update_message,
    send_signal,
    send_text_to_all,
)
from services.trade_tracker import TradeTracker
from services.execution_service import ExecutionService
from utils.logger import setup_logger

logger = setup_logger()


class MarketScanner:
    def __init__(self):
        self.client = BinanceFuturesClient()
        self.engine = SignalEngine()
        self.news_guard = NewsGuard()
        self.state = StateStore()
        self.signal_log = SignalLogStore()
        self.trade_tracker = TradeTracker()
        self.paper = PaperTrader()
        self.btc_filter = BTCFilter()
        self.execution = ExecutionService()
        self._scan_lock = asyncio.Lock()
        self._trade_monitor_lock = asyncio.Lock()

        self.last_cycle_info = {
            "started_at": None,
            "finished_at": None,
            "symbols_checked": 0,
            "signals_found": 0,
            "news_block": False,
            "news_reason": "unknown",
            "sentiment": "NEUTRAL",
            "btc_bias": "NEUTRAL",
            "skip_summary": {},
            "top_signal_symbols": [],
        }

    def _make_cooldown_key(self, symbol: str, direction: str) -> str:
        return f"{symbol}:{direction}"

    def _make_signal_key(self, symbol: str, direction: str) -> str:
        return f"{symbol}:{direction}"

    async def _is_on_cooldown(self, symbol: str, direction: str) -> bool:
        key = self._make_cooldown_key(symbol, direction)
        return await self.state.get_cooldown(key) is not None

    async def _set_cooldown(self, symbol: str, direction: str):
        key = self._make_cooldown_key(symbol, direction)
        await self.state.set_cooldown(key, Config.SIGNAL_COOLDOWN_MINUTES)

    async def _same_setup(self, signal: Signal) -> bool:
        key = self._make_signal_key(signal.symbol, signal.direction)
        previous = await self.state.get_last_signal(key)

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

    async def _remember_signal(self, signal: Signal):
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
        await self.state.set_last_signal(key, payload)

    async def _log_signal_to_history(self, signal: Signal):
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
        await self.signal_log.add_signal(payload)

    async def _track_new_signal(self, signal: Signal, execution_report: dict | None = None):
        execution_report = execution_report or {}
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
            "entry_price": execution_report.get("entry_price"),
            "initial_position_qty": execution_report.get("qty"),
            "tp1_qty": execution_report.get("tp1_qty"),
            "tp2_qty": execution_report.get("tp2_qty"),
            "tp3_qty": execution_report.get("tp3_qty"),
        }
        await self.trade_tracker.add_signal(payload)

    async def get_last_logged_signals(self, limit: int = 5) -> list[dict]:
        return await self.signal_log.get_last_signals(limit=limit)

    async def get_open_signals(self) -> list[dict]:
        return await self.trade_tracker.get_open_signals()

    async def get_stats(self) -> dict:
        return await self.trade_tracker.get_stats()

    async def get_pair_stats(self) -> list[dict]:
        return await self.trade_tracker.get_pair_stats()

    async def get_best_pairs(self, min_closed: int = 1, limit: int = 5) -> list[dict]:
        return await self.trade_tracker.get_best_pairs(min_closed=min_closed, limit=limit)

    async def get_symbol_whitelist(self) -> list[dict]:
        return await self.trade_tracker.get_symbol_whitelist()

    async def refresh_symbol_whitelist(self) -> list[dict]:
        return await self.trade_tracker.refresh_symbol_whitelist()

    async def get_side_stats(self) -> dict:
        return await self.trade_tracker.get_side_stats()

    async def get_daily_report(self) -> list[dict]:
        return await self.trade_tracker.get_daily_report()

    async def get_weekly_report(self) -> list[dict]:
        return await self.trade_tracker.get_weekly_report()

    async def get_paper_stats(self) -> dict:
        return await self.paper.stats()

    async def get_paper_open_trades(self) -> list[dict]:
        return await self.paper.get_open_trades()

    async def get_paper_history(self, limit: int = 10) -> list[dict]:
        return await self.paper.get_last_closed(limit)

    async def get_open_orders(self) -> list[dict]:
        if not self.execution.enabled():
            return []

        return await self.execution.get_open_orders()

    async def get_heartbeat(self) -> dict:
        return {
            "mode": Config.STRATEGY_MODE,
            "scan_interval": Config.SCAN_INTERVAL_SECONDS,
            "open_signals": len(await self.get_open_signals()),
            "last_cycle": self.last_cycle_info,
            "paper_stats": await self.paper.stats(),
        }

    async def _send_closed_signal_notifications(self, bot: Bot):
        items = await self.trade_tracker.get_unnotified_closed_signals()

        for item in items:
            try:
                text = format_result_message(item)
                await send_text_to_all(bot, Config.CHAT_IDS, text)
                await self.trade_tracker.mark_notified(item["id"])
                logger.info(f"[NOTIFY] Отправлен результат сигнала {item['symbol']} -> {item['status']}")
            except Exception as error:
                logger.exception(f"[NOTIFY ERROR] {item.get('symbol')} | {error}")

    def _detect_trade_event(
        self,
        item: dict,
        high: float,
        low: float,
    ) -> str | None:
        direction = item["direction"]
        stage = item.get("protection_stage") or "INITIAL"
        stop_loss = float(item.get("active_stop_loss") or item["stop_loss"])
        tp1 = float(item["tp1"])
        tp2 = float(item["tp2"])
        tp3 = float(item["tp3"])

        if direction == "LONG":
            if low <= stop_loss:
                return "STOP_HIT"
            if high >= tp3:
                return "TP3_HIT"
            if stage != "TP2_HIT" and high >= tp2:
                return "TP2_HIT"
            if stage == "INITIAL" and high >= tp1:
                return "TP1_HIT"
            return None

        if high >= stop_loss:
            return "STOP_HIT"
        if low <= tp3:
            return "TP3_HIT"
        if stage != "TP2_HIT" and low <= tp2:
            return "TP2_HIT"
        if stage == "INITIAL" and low <= tp1:
            return "TP1_HIT"

        return None

    def _qty_tracking_ready(self, item: dict) -> bool:
        return all(
            item.get(key) is not None
            for key in ("initial_position_qty", "tp1_qty", "tp2_qty", "tp3_qty")
        )

    def _qty_tolerance(self, item: dict) -> float:
        initial_qty = float(item.get("initial_position_qty") or 0.0)
        tp3_qty = float(item.get("tp3_qty") or 0.0)
        return max(initial_qty * 0.01, tp3_qty * 0.5, 1e-12)

    def _position_confirms_target(self, item: dict, target_status: str, position_qty: float) -> bool:
        if not self._qty_tracking_ready(item):
            return False

        initial_qty = float(item["initial_position_qty"])
        tp1_qty = float(item["tp1_qty"])
        tp2_qty = float(item["tp2_qty"])
        tolerance = self._qty_tolerance(item)

        if target_status == "TP1_HIT":
            expected_qty = max(initial_qty - tp1_qty, 0.0)
            return position_qty <= expected_qty + tolerance

        if target_status == "TP2_HIT":
            expected_qty = max(initial_qty - tp1_qty - tp2_qty, 0.0)
            return position_qty <= expected_qty + tolerance

        return False

    def _infer_final_event(self, item: dict, mark_price: float) -> str:
        direction = item["direction"]
        tp3 = float(item["tp3"])

        if direction == "LONG":
            return "TP3_HIT" if mark_price >= tp3 else "STOP_HIT"

        return "TP3_HIT" if mark_price <= tp3 else "STOP_HIT"

    def _breakeven_price(self, item: dict) -> float:
        entry_price = item.get("entry_price")
        if entry_price is not None:
            return float(entry_price)

        return (float(item["entry_min"]) + float(item["entry_max"])) / 2.0

    def _detect_trade_event_from_position(
        self,
        item: dict,
        position_qty: float,
        mark_price: float,
    ) -> str | None:
        if not self._qty_tracking_ready(item):
            return None

        stage = item.get("protection_stage") or "INITIAL"
        initial_qty = float(item["initial_position_qty"])
        tp1_qty = float(item["tp1_qty"])
        tp2_qty = float(item["tp2_qty"])
        tolerance = self._qty_tolerance(item)

        if position_qty <= tolerance:
            return self._infer_final_event(item, mark_price)

        tp1_remaining_qty = max(initial_qty - tp1_qty, 0.0)
        tp2_remaining_qty = max(initial_qty - tp1_qty - tp2_qty, 0.0)

        if stage != "TP2_HIT" and position_qty <= tp2_remaining_qty + tolerance:
            return "TP2_HIT"

        if stage == "INITIAL" and position_qty <= tp1_remaining_qty + tolerance:
            return "TP1_HIT"

        return None

    async def _replace_protection_after_target(
        self,
        item: dict,
        target_status: str,
    ):
        if not self.execution.enabled():
            return None

        symbol = item["symbol"]
        direction = item["direction"]
        tp1 = float(item["tp1"])
        tp2 = float(item["tp2"])
        tp3 = float(item["tp3"])

        if target_status == "TP1_HIT":
            entry_price = self._breakeven_price(item)
            return await self.execution.move_stop_after_tp1(
                symbol,
                direction,
                entry_price,
                tp1,
                tp2,
                tp3,
            )

        if target_status == "TP2_HIT":
            return await self.execution.move_stop_after_tp2(
                symbol,
                direction,
                tp1,
                tp3,
            )

        return None

    async def _cancel_protection_after_final_close(self, item: dict):
        if not self.execution.enabled():
            return None

        symbol = item["symbol"]
        return await self.execution.cancel_all_algo_orders(symbol)

    async def _handle_trade_event(
        self,
        bot: Bot,
        item: dict,
        event: str,
        position_qty: float | None = None,
    ):
        symbol = item["symbol"]
        direction = item["direction"]

        if event in {"TP1_HIT", "TP2_HIT"}:
            new_stop = self._breakeven_price(item) if event == "TP1_HIT" else float(item["tp1"])
            protection_updated = True

            if self.execution.enabled():
                if position_qty is None:
                    position_qty = await self.execution.get_position_qty(symbol)

                if not self._position_confirms_target(item, event, position_qty):
                    logger.warning(
                        f"[SMART SL] {symbol} {direction} {event} цена была достигнута, "
                        f"но уменьшение позиции еще не подтверждено qty={position_qty}"
                    )
                    return

                try:
                    protection_updated = await self._replace_protection_after_target(item, event) is not None
                except Exception as error:
                    protection_updated = False
                    logger.exception(f"[SMART SL ERROR] {symbol} {direction} {event} | {error}")

            if not protection_updated:
                logger.warning(
                    f"[SMART SL] {symbol} {direction} {event} не подтвержден, этап не обновляю"
                )
                return

            updated = await self.trade_tracker.mark_target_hit(
                item["id"],
                event,
                new_stop,
            )

            if updated:
                logger.info(f"[TRACKER] {symbol} {direction} -> {event}, signal remains OPEN")
                await send_text_to_all(
                    bot,
                    Config.CHAT_IDS,
                    format_trade_update_message(updated, event, self.execution.enabled()),
                )
            return

        try:
            if self.execution.enabled():
                qty = await self.execution.get_position_qty(symbol)
                if qty > 0:
                    logger.warning(
                        f"[AUTO TRADE CLEANUP] {symbol} {direction} {event} не подтвержден, позиция qty={qty}"
                    )
                    return

            await self._cancel_protection_after_final_close(item)
        except Exception as error:
            logger.exception(f"[AUTO TRADE CLEANUP ERROR] {symbol} {direction} {event} | {error}")
            return

        await self.trade_tracker.update_signal(item["id"], event)
        logger.info(f"[TRACKER] {symbol} {direction} -> {event}")

    async def check_open_signals(self, bot: Bot, use_live_price: bool = False):
        async with self._trade_monitor_lock:
            open_signals = await self.trade_tracker.get_open_signals()

            for item in open_signals:
                try:
                    symbol = item["symbol"]

                    if use_live_price:
                        mark_price = await self.execution.get_mark_price(symbol)
                        position_qty = None

                        if self.execution.enabled():
                            position_qty = await self.execution.get_position_qty(symbol)
                            event = self._detect_trade_event_from_position(
                                item,
                                position_qty,
                                mark_price,
                            )
                        else:
                            event = self._detect_trade_event(item, mark_price, mark_price)

                        if event:
                            await self._handle_trade_event(bot, item, event, position_qty)
                        continue

                    ltf_df = await self.client.get_klines(symbol, Config.LTF_INTERVAL, 5)
                    if len(ltf_df) < 2:
                        continue

                    last_closed = ltf_df.iloc[-2]
                    high = float(last_closed["high"])
                    low = float(last_closed["low"])

                    event = self._detect_trade_event(item, high, low)

                    if event:
                        await self._handle_trade_event(bot, item, event)

                except Exception as error:
                    logger.exception(f"[TRACKER ERROR] {item.get('symbol')} | {error}")

            await self._send_closed_signal_notifications(bot)

    async def monitor_open_signals(self, bot: Bot):
        await self.check_open_signals(bot, use_live_price=True)

    def _format_diag(self, diagnostics: dict) -> str:
        if not diagnostics:
            return ""

        parts = []

        for label, key in [
            ("ADX4h", "htf_adx"),
            ("ADX1h", "mtf_adx"),
            ("RSI15m", "ltf_rsi"),
            ("MACD15m", "ltf_macd_hist"),
            ("ATRr15m", "ltf_atr_ratio"),
            ("Vol15m", "ltf_quote_volume_ratio"),
            ("RR", "rr"),
            ("Risk", "risk_pct"),
            ("ResGap", "resistance_gap"),
            ("SupGap", "support_gap"),
            ("BTC", "btc_bias"),
            ("Setup", "setup_type"),
            ("HTF", "htf_regime"),
            ("Liq", "liquidity_profile"),
        ]:
            value = diagnostics.get(key)
            if value is not None:
                parts.append(f"{label}={value}")

        return " | " + ", ".join(parts) if parts else ""

    async def _load_liquid_symbols(self) -> list[str]:
        try:
            symbols = await self.client.get_liquid_symbols()
            if symbols:
                logger.info(f"После фильтра ликвидности выбрано пар: {len(symbols)}")
                return symbols
        except Exception as error:
            logger.exception(f"Не удалось загрузить ликвидные пары: {error}")

        logger.info("Использую резервный список пар из config.py")
        return Config.DEFAULT_SYMBOLS

    async def _load_symbols_for_scan(self) -> list[str]:
        liquid_symbols = await self._load_liquid_symbols()

        if not Config.AUTO_WHITELIST_ENABLED:
            return liquid_symbols

        try:
            if await self.trade_tracker.whitelist_is_stale():
                refreshed = await self.trade_tracker.refresh_symbol_whitelist()
                logger.info(f"[WHITELIST] Переоценка завершена, символов={len(refreshed)}")

            whitelist = await self.trade_tracker.get_symbol_whitelist()
            whitelist_symbols = [item["symbol"] for item in whitelist]

            if not whitelist_symbols:
                logger.info("[WHITELIST] Недостаточно статистики, сканирую ликвидные пары")
                return liquid_symbols

            allowed = set(whitelist_symbols)
            filtered = [symbol for symbol in liquid_symbols if symbol in allowed]

            if not filtered:
                logger.warning("[WHITELIST] Топ-символы не прошли фильтр ликвидности, использую сохраненный whitelist")
                return whitelist_symbols[: Config.AUTO_WHITELIST_SIZE]

            logger.info(f"[WHITELIST] Сканирую {len(filtered)} пар из авто-whitelist")
            return filtered[: Config.AUTO_WHITELIST_SIZE]

        except Exception as error:
            logger.exception(f"[WHITELIST ERROR] {error}")
            return liquid_symbols

    async def _log_paper_stats(self):
        stats = await self.paper.stats()
        logger.info(
            "[PAPER STATS] "
            f"balance={stats['balance']}$ | pnl={stats['pnl_usdt']}$ | "
            f"R={stats['total_r']} | trades={stats['total_trades']} | "
            f"open={stats['open_trades']} | closed={stats['closed_trades']} | "
            f"wins={stats['wins']} | losses={stats['losses']} | "
            f"winrate={stats['winrate']}%"
        )

    async def _portfolio_allows_new_signal(self, signal: Signal) -> tuple[bool, str]:
        stats = await self.paper.stats()
        balance = float(stats.get("balance") or 0.0)
        open_trades = int(stats.get("open_trades") or 0)
        open_risk = float(stats.get("open_risk_usdt") or 0.0)
        open_volume = float(stats.get("open_volume_usdt") or 0.0)
        next_risk = balance * float(stats.get("risk_per_trade") or 0.0)

        max_risk = balance * Config.MAX_TOTAL_OPEN_RISK_PCT
        max_volume = balance * Config.MAX_OPEN_VOLUME_TO_BALANCE

        if open_trades >= Config.MAX_OPEN_TRADES:
            return False, f"portfolio: максимум открытых сделок ({open_trades}/{Config.MAX_OPEN_TRADES})"

        if balance > 0 and open_risk + next_risk > max_risk:
            return False, f"portfolio: лимит открытого риска ({open_risk + next_risk:.2f}$/{max_risk:.2f}$)"

        if balance > 0 and open_volume >= max_volume:
            return False, f"portfolio: перегрузка объёма ({open_volume:.2f}$/{max_volume:.2f}$)"

        return True, ""

    async def _side_allows_signal(self, signal: Signal) -> tuple[bool, str]:
        if not Config.SIDE_QUALITY_FILTER_ENABLED:
            return True, ""

        side_stats = await self.get_side_stats()
        stats = side_stats.get(signal.direction, {})
        closed = int(stats.get("closed") or 0)

        if closed < Config.SIDE_QUALITY_MIN_CLOSED_TRADES:
            return True, ""

        expectancy = float(stats.get("expectancy") or 0.0)
        stop_rate = float(stats.get("stop_rate") or 0.0)

        if expectancy <= Config.SIDE_QUALITY_MIN_EXPECTANCY:
            return (
                False,
                f"side quality: {signal.direction} expectancy {expectancy:.2f}R хуже лимита",
            )

        if stop_rate >= Config.SIDE_QUALITY_MAX_STOP_RATE and expectancy <= 0:
            return (
                False,
                f"side quality: {signal.direction} stop-rate {stop_rate:.1f}% слишком высокий",
            )

        return True, ""

    async def _update_paper_trades_from_symbol(self, symbol: str):
        try:
            ltf_df = await self.client.get_klines(symbol, Config.LTF_INTERVAL, 5)
            if len(ltf_df) < 2:
                return

            last_closed = ltf_df.iloc[-2]
            high = float(last_closed["high"])
            low = float(last_closed["low"])

            closed_now = await self.paper.update_symbol_price(symbol, high, low)

            for trade in closed_now:
                logger.info(
                    f"[PAPER CLOSED] {trade.symbol} {trade.direction} {trade.close_reason} | "
                    f"type={trade.signal_type} | result={trade.result_usdt}$ | R={trade.result_r}"
                )

        except Exception as error:
            logger.exception(f"[PAPER UPDATE ERROR] {symbol} | {error}")

    async def _get_btc_bias(self) -> str:
        try:
            btc_df = await self.client.get_klines("BTCUSDT", Config.LTF_INTERVAL, Config.KLINES_LIMIT)
            if len(btc_df) < 60:
                return "NEUTRAL"

            btc_df = self.engine.prepare_dataframe(btc_df)
            return self.btc_filter.get_bias(btc_df)
        except Exception as error:
            logger.exception(f"[BTC FILTER ERROR] {error}")
            return "NEUTRAL"

    async def scan_market(self, bot: Bot, send_to_telegram: bool = True) -> List[SignalCheckResult]:
        async with self._scan_lock:
            await self.check_open_signals(bot)

            cycle_started_at = datetime.utcnow().isoformat()
            news_decision = await self.news_guard.evaluate_market()
            btc_bias = await self._get_btc_bias()

            logger.info(
                f"Старт сканирования рынка... режим={Config.STRATEGY_MODE} | "
                f"news_block={news_decision.blocked} | sentiment={news_decision.sentiment_bias} | "
                f"news_reason={news_decision.reason} | btc_bias={btc_bias}"
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
                    "btc_bias": btc_bias,
                    "skip_summary": {"news block": 1},
                    "top_signal_symbols": [],
                }

                if send_to_telegram and Config.SEND_NEWS_BLOCK_MESSAGE:
                    await send_text_to_all(
                        bot,
                        Config.CHAT_IDS,
                        f"🛑 News block\n\nПричина: {news_decision.reason}\nSentiment: {news_decision.sentiment_bias}",
                    )

                await self._log_paper_stats()
                return []

            symbols = await self._load_symbols_for_scan()
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
                        result.signal.diagnostics["btc_bias"] = btc_bias

                        allow_btc, btc_reason = self.btc_filter.allow_trade(result.signal.direction, btc_bias)
                        if not allow_btc:
                            if Config.BTC_HARD_FILTER_ENABLED:
                                result = SignalCheckResult(
                                    symbol=symbol,
                                    signal=None,
                                    skip_reason=btc_reason,
                                    diagnostics=result.signal.diagnostics,
                                )
                            else:
                                result.signal.score = round(
                                    result.signal.score - Config.BTC_COUNTER_TREND_PENALTY,
                                    1,
                                )
                                result.signal.reasons.append(
                                    f"BTC filter: counter-trend penalty -{Config.BTC_COUNTER_TREND_PENALTY}"
                                )
                                signal_type = self.engine.classify_signal(
                                    result.signal.score,
                                    float(result.signal.diagnostics.get("rr") or 0.0),
                                )
                                if not signal_type:
                                    result = SignalCheckResult(
                                        symbol=symbol,
                                        signal=None,
                                        skip_reason=f"{btc_reason}, после штрафа сигнал слабый",
                                        diagnostics=result.signal.diagnostics,
                                    )
                                else:
                                    result.signal.signal_type = signal_type

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
                        if "btc_bias" not in result.diagnostics:
                            result.diagnostics["btc_bias"] = btc_bias

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
                if await self._is_on_cooldown(signal.symbol, signal.direction):
                    logger.info(f"[COOLDOWN] {signal.symbol} {signal.direction} | повторный сигнал пропущен")
                    skip_counter["cooldown"] += 1
                    continue

                if await self._same_setup(signal):
                    logger.info(f"[DUPLICATE] {signal.symbol} {signal.direction} | тот же сетап, пропускаю")
                    skip_counter["duplicate setup"] += 1
                    continue

                final_signals.append(signal)

            top_signals = final_signals[: Config.MAX_SIGNALS_PER_SCAN]
            sent_signal_symbols = []

            for signal in top_signals:
                try:
                    side_ok, side_reason = await self._side_allows_signal(signal)
                    if not side_ok:
                        logger.info(f"[SIDE QUALITY SKIP] {signal.symbol} {signal.direction} | {side_reason}")
                        skip_counter[side_reason] += 1
                        continue

                    portfolio_ok, portfolio_reason = await self._portfolio_allows_new_signal(signal)
                    if not portfolio_ok:
                        logger.info(f"[PORTFOLIO SKIP] {signal.symbol} | {portfolio_reason}")
                        skip_counter[portfolio_reason] += 1
                        continue

                    execution_report = None

                    if send_to_telegram:
                        await send_signal(bot, Config.CHAT_IDS, signal)

                    if Config.AUTO_TRADE:
                        execution_report = await self.execution.execute_signal(
                            bot,
                            Config.CHAT_IDS,
                            signal,
                        )

                    await self._set_cooldown(signal.symbol, signal.direction)
                    await self._remember_signal(signal)
                    await self._log_signal_to_history(signal)
                    await self._track_new_signal(signal, execution_report)

                    paper_trade = await self.paper.open_trade(signal)
                    if paper_trade:
                        logger.info(
                            f"[PAPER OPEN] {paper_trade.symbol} {paper_trade.direction} {paper_trade.signal_type} | "
                            f"entry={round(paper_trade.entry_price, 6)} | "
                            f"risk={round(paper_trade.risk_amount, 2)}$ | "
                            f"size={round(paper_trade.size, 2)}"
                        )

                    logger.info(f"Сигнал отправлен: {signal.symbol}")
                    sent_signal_symbols.append(signal.symbol)
                except Exception as error:
                    logger.exception(f"Ошибка отправки сигнала {signal.symbol}: {error}")

            self.last_cycle_info = {
                "started_at": cycle_started_at,
                "finished_at": datetime.utcnow().isoformat(),
                "symbols_checked": len(symbols),
                "signals_found": len(sent_signal_symbols),
                "news_block": False,
                "news_reason": news_decision.reason,
                "sentiment": news_decision.sentiment_bias,
                "btc_bias": btc_bias,
                "skip_summary": dict(skip_counter),
                "top_signal_symbols": sent_signal_symbols,
            }

            if not sent_signal_symbols:
                logger.info("Сильных новых сигналов не найдено.")

            await self._log_paper_stats()
            return results
