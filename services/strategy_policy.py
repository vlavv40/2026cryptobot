from dataclasses import dataclass, field

from config import Config


@dataclass
class StrategyContext:
    btc_bias: str
    sentiment_bias: str
    paper_stats: dict
    side_stats: dict
    open_trades: list[dict]


@dataclass
class StrategyDecision:
    allowed: bool
    reason: str
    risk_multiplier: float = 1.0
    score_delta: float = 0.0
    tags: list[str] = field(default_factory=list)


class StrategyPolicy:
    MEME_KEYWORDS = (
        "1000",
        "DOGE",
        "PEPE",
        "SHIB",
        "FLOKI",
        "BONK",
        "TRUMP",
        "PUMP",
        "USELESS",
    )

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            if value in {None, ""}:
                return default
            if value == "∞":
                return 999.0
            return float(value)
        except Exception:
            return default

    def _safe_int(self, value, default: int = 0) -> int:
        try:
            if value in {None, ""}:
                return default
            return int(value)
        except Exception:
            return default

    def _same_direction_open(self, direction: str, open_trades: list[dict]) -> int:
        return sum(
            1
            for trade in open_trades
            if trade.get("status") == "OPEN" and trade.get("direction") == direction
        )

    def _is_meme_symbol(self, symbol: str) -> bool:
        symbol = symbol.upper()
        return any(keyword in symbol for keyword in self.MEME_KEYWORDS)

    def _counter_to_btc(self, direction: str, btc_bias: str) -> bool:
        return (
            (btc_bias == "BEARISH" and direction == "LONG")
            or (btc_bias == "BULLISH" and direction == "SHORT")
        )

    def _counter_to_sentiment(self, direction: str, sentiment_bias: str) -> bool:
        return (
            (sentiment_bias == "BEARISH" and direction == "LONG")
            or (sentiment_bias == "BULLISH" and direction == "SHORT")
        )

    def _edge_is_broken(self, context: StrategyContext) -> bool:
        closed = self._safe_int(context.paper_stats.get("closed_trades"))
        if closed < Config.POLICY_MIN_TRADES_FOR_EDGE:
            return False

        expectancy = self._safe_float(context.paper_stats.get("expectancy"))
        profit_factor = self._safe_float(context.paper_stats.get("profit_factor"))

        return (
            expectancy <= Config.POLICY_MIN_EXPECTANCY_R
            and profit_factor < Config.POLICY_MIN_PROFIT_FACTOR
        )

    def evaluate_signal(self, signal, context: StrategyContext) -> StrategyDecision:
        if not Config.STRATEGY_POLICY_ENABLED:
            return StrategyDecision(True, "strategy policy disabled")

        total_r = self._safe_float(context.paper_stats.get("total_r"))
        max_drawdown = self._safe_float(context.paper_stats.get("max_drawdown"))

        if total_r <= -abs(Config.POLICY_MAX_SESSION_LOSS_R):
            return StrategyDecision(
                False,
                f"strategy policy: risk-off, session loss {total_r:.2f}R",
                tags=["RISK_OFF"],
            )

        if max_drawdown >= abs(Config.POLICY_MAX_DRAWDOWN_R):
            return StrategyDecision(
                False,
                f"strategy policy: risk-off, drawdown {max_drawdown:.2f}R",
                tags=["RISK_OFF"],
            )

        if self._edge_is_broken(context):
            return StrategyDecision(
                False,
                "strategy policy: paper edge пока минусовой, новые сделки на паузе",
                tags=["EDGE_PAUSE"],
            )

        same_direction_open = self._same_direction_open(signal.direction, context.open_trades)
        if same_direction_open >= Config.POLICY_MAX_SAME_DIRECTION_OPEN:
            return StrategyDecision(
                False,
                (
                    "strategy policy: слишком много открытых сделок "
                    f"в сторону {signal.direction}"
                ),
                tags=["CONCENTRATION_BLOCK"],
            )

        risk_multiplier = 1.0
        score_delta = 0.0
        tags: list[str] = []
        reasons: list[str] = []

        if getattr(signal, "signal_type", "SETUP") == "SETUP":
            risk_multiplier *= Config.POLICY_SETUP_RISK_MULTIPLIER
            tags.append("SETUP_RISK")

        if self._counter_to_btc(signal.direction, context.btc_bias):
            risk_multiplier *= Config.POLICY_COUNTER_BTC_RISK_MULTIPLIER
            score_delta -= 0.3
            tags.append("BTC_COUNTER")
            reasons.append("BTC против направления, риск снижен")

        if self._counter_to_sentiment(signal.direction, context.sentiment_bias):
            risk_multiplier *= 0.70
            score_delta -= 0.2
            tags.append("SENTIMENT_COUNTER")
            reasons.append("новостной фон против направления, риск снижен")

        if self._is_meme_symbol(signal.symbol):
            risk_multiplier *= Config.POLICY_MEME_RISK_MULTIPLIER
            tags.append("HIGH_BETA")
            reasons.append("high-beta/meme тикер, риск снижен")

        risk_pct = self._safe_float(signal.diagnostics.get("risk_pct"))
        if risk_pct >= 0.035:
            risk_multiplier *= 0.75
            tags.append("WIDE_STOP")
            reasons.append("широкий стоп относительно цены, риск снижен")

        risk_multiplier = max(
            Config.POLICY_MIN_RISK_MULTIPLIER,
            min(1.0, risk_multiplier),
        )

        if risk_multiplier < 1.0 and not reasons:
            reasons.append("системный риск снижен policy-layer")

        reason = "; ".join(reasons) if reasons else "strategy policy: allowed"

        return StrategyDecision(
            True,
            reason,
            risk_multiplier=round(risk_multiplier, 3),
            score_delta=score_delta,
            tags=tags,
        )
