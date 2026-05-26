from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from config import Config
from utils.logger import setup_logger


logger = setup_logger()


@dataclass
class NewsGuardDecision:
    blocked: bool
    reason: str
    sentiment_bias: str  # BULLISH / BEARISH / NEUTRAL
    macro_events: list[dict]
    negative_count: int
    positive_count: int
    impact_score: int
    severity: str
    impact_reasons: list[str]


@dataclass
class HeadlineImpact:
    sentiment_bias: str
    negative_count: int
    positive_count: int
    impact_score: int
    positive_score: int
    severity: str
    reasons: list[str]


class NewsGuard:
    def __init__(self):
        self.fmp_api_key = Config.FMP_API_KEY
        self.news_api_key = Config.NEWS_API_KEY

    async def evaluate_market(self) -> NewsGuardDecision:
        if not Config.NEWS_GUARD_ENABLED:
            return NewsGuardDecision(
                blocked=False,
                reason="news guard disabled",
                sentiment_bias="NEUTRAL",
                macro_events=[],
                negative_count=0,
                positive_count=0,
                impact_score=0,
                severity="LOW",
                impact_reasons=[],
            )

        macro_events = await self._load_macro_events()
        macro_block_reason = self._macro_block_reason(macro_events)

        sentiment_bias = "NEUTRAL"
        negative_count = 0
        positive_count = 0
        impact_score = 0
        severity = "LOW"
        impact_reasons = []

        if Config.NEWS_SENTIMENT_ENABLED:
            headline_impact = await self._load_crypto_headline_bias()
            sentiment_bias = headline_impact.sentiment_bias
            negative_count = headline_impact.negative_count
            positive_count = headline_impact.positive_count
            impact_score = headline_impact.impact_score
            severity = headline_impact.severity
            impact_reasons = headline_impact.reasons

        sentiment_block_reason = None
        if (
            Config.NEWS_SENTIMENT_BLOCKS_MARKET
            and severity in {"HIGH", "CRITICAL"}
            and sentiment_bias == "BEARISH"
        ):
            sentiment_block_reason = (
                f"crypto news impact block: severity={severity}, "
                f"score={impact_score}, negative={negative_count}, "
                f"positive={positive_count}"
            )

        blocked = macro_block_reason is not None or sentiment_block_reason is not None

        return NewsGuardDecision(
            blocked=blocked,
            reason=macro_block_reason or sentiment_block_reason or "ok",
            sentiment_bias=sentiment_bias,
            macro_events=macro_events,
            negative_count=negative_count,
            positive_count=positive_count,
            impact_score=impact_score,
            severity=severity,
            impact_reasons=impact_reasons,
        )

    async def _load_macro_events(self) -> list[dict]:
        if not self.fmp_api_key:
            return []

        now = datetime.now(timezone.utc)
        start = (now - timedelta(minutes=Config.NEWS_COOLDOWN_AFTER_MINUTES)).strftime("%Y-%m-%d")
        end = (now + timedelta(days=2)).strftime("%Y-%m-%d")

        url = (
            "https://financialmodelingprep.com/stable/economic-calendar"
            f"?from={start}&to={end}&apikey={self.fmp_api_key}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=20) as response:
                    if response.status != 200:
                        logger.warning(f"[NEWS GUARD] FMP error status={response.status}")
                        return []
                    data = await response.json()

            if not isinstance(data, list):
                logger.warning(f"[NEWS GUARD] FMP unexpected payload type={type(data).__name__}")
                return []

            return data
        except Exception as error:
            logger.warning(f"[NEWS GUARD] FMP request failed: {error}")
            return []

    def _macro_block_reason(self, events: list[dict]) -> Optional[str]:
        if not events:
            return None

        now = datetime.now(timezone.utc)

        high_impact_keywords = [
            "cpi",
            "inflation",
            "fomc",
            "interest rate",
            "rate decision",
            "federal funds",
            "nfp",
            "nonfarm payrolls",
            "powell",
            "ecb",
            "boe",
            "boj",
            "gdp",
            "trump",
            "tariff",
            "tariffs",
            "trade war",
            "iran",
            "israel",
            "hormuz",
            "oil shock",
            "sanction",
            "sanctions",
            "war",
            "conflict",
            "attack",
            "strike",
        ]

        for event in events:
            try:
                event_name = str(
                    event.get("event")
                    or event.get("title")
                    or event.get("name")
                    or ""
                ).lower()

                country = str(event.get("country", "")).upper()

                date_str = event.get("date") or event.get("datetime")
                if not date_str:
                    continue

                event_dt = self._parse_dt(date_str)
                if event_dt is None:
                    continue

                delta_minutes = (event_dt - now).total_seconds() / 60

                is_high_impact = any(keyword in event_name for keyword in high_impact_keywords)

                if Config.BLOCK_HIGH_IMPACT_NEWS_ONLY and not is_high_impact:
                    continue

                if -Config.NEWS_COOLDOWN_AFTER_MINUTES <= delta_minutes <= Config.NEWS_LOOKAHEAD_MINUTES:
                    return (
                        f"macro news block: {country} | {event_name} | "
                        f"{int(delta_minutes)} min"
                    )
            except Exception:
                continue

        return None

    async def _load_crypto_headline_bias(self) -> HeadlineImpact:
        if not self.news_api_key:
            return HeadlineImpact("NEUTRAL", 0, 0, 0, 0, "LOW", [])

        query = (
            '(bitcoin OR btc OR ethereum OR eth OR crypto OR cryptocurrency '
            'OR binance OR sec OR etf OR fed OR rates OR trump OR tariff '
            'OR tariffs OR iran OR israel OR oil OR hormuz OR war OR conflict '
            'OR sanctions)'
        )

        url = "https://newsapi.org/v2/everything"

        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": self.news_api_key,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=20) as response:
                    if response.status != 200:
                        logger.warning(f"[NEWS GUARD] NewsAPI error status={response.status}")
                        return HeadlineImpact("NEUTRAL", 0, 0, 0, 0, "LOW", [])
                    data = await response.json()

            articles = data.get("articles", [])
            if not isinstance(articles, list):
                logger.warning("[NEWS GUARD] NewsAPI returned non-list articles")
                return HeadlineImpact("NEUTRAL", 0, 0, 0, 0, "LOW", [])

            return self._classify_headline_bias(articles)

        except Exception as error:
            logger.warning(f"[NEWS GUARD] NewsAPI request failed: {error}")
            return HeadlineImpact("NEUTRAL", 0, 0, 0, 0, "LOW", [])

    def _classify_headline_bias(self, articles: list[dict]) -> HeadlineImpact:
        trusted_sources = [
            "reuters", "bloomberg", "associated press", "ap news", "cnbc",
            "wall street journal", "wsj", "financial times", "ft",
            "coindesk", "the block", "cointelegraph", "decrypt",
        ]
        market_terms = [
            "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
            "binance", "coinbase", "solana", "xrp", "etf", "markets",
            "market", "stocks", "nasdaq", "s&p", "sp500", "risk-off",
            "liquidation", "liquidations",
        ]
        market_move_words = [
            "fall", "falls", "fell", "drop", "drops", "dropped", "slide",
            "slides", "slump", "slumps", "plunge", "plunges", "tumble",
            "tumbles", "selloff", "sell-off", "crash", "crashes", "dump",
            "dumps", "rout", "liquidation", "liquidations", "risk-off",
            "volatility", "wipes out",
        ]
        critical_words = [
            "fomc", "cpi", "pce", "nfp", "nonfarm payrolls", "powell",
            "rate decision", "interest rate", "federal reserve",
            "sec lawsuit", "sues", "charges", "criminal probe",
            "bankruptcy", "insolvent", "insolvency", "withdrawal halt",
            "halt withdrawals", "depeg", "de-pegged", "hack", "exploit",
            "etf rejected", "etf denial",
        ]
        geopolitical_words = [
            "trump", "tariff", "tariffs", "trade war", "iran", "israel",
            "hormuz", "oil shock", "sanction", "sanctions", "war",
            "conflict", "attack", "strike", "missile", "escalation",
        ]
        negative_words = [
            "ban", "lawsuit", "hack", "war", "attack", "collapse",
            "liquidation", "recession", "crackdown", "fraud", "selloff",
            "tariff", "tariffs", "trade war", "conflict", "sanction",
            "sanctions", "iran", "israel", "hormuz", "oil shock",
            "strike", "missile", "panic", "crash", "plunge", "dump",
            "risk-off", "escalation",
        ]
        positive_words = [
            "approval", "launch", "growth", "surge", "bullish", "rally",
            "adoption", "buy", "inflow", "upgrade", "partnership",
            "easing", "cut rates", "peace", "ceasefire", "deal",
            "agreement", "de-escalation",
        ]

        negative_count = 0
        positive_count = 0
        impact_score = 0
        positive_score = 0
        reasons = []
        seen_titles = set()
        critical_article_seen = False

        for article in articles:
            title = str(article.get("title", "") or "")
            normalized_title = title.strip().lower()
            if not normalized_title or normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)

            source_name = str((article.get("source") or {}).get("name", "") or "").lower()
            text = (
                f"{title} {article.get('description', '')} {source_name}"
            ).lower()

            trusted = any(source in source_name for source in trusted_sources)
            has_market_context = any(word in text for word in market_terms)
            has_market_move = any(word in text for word in market_move_words)
            has_critical = any(word in text for word in critical_words)
            has_geopolitical = any(word in text for word in geopolitical_words)
            has_negative = any(word in text for word in negative_words)
            has_positive = any(word in text for word in positive_words)

            article_score = 0
            if has_critical:
                article_score += 4 if has_market_context or trusted else 2
            if has_market_context and has_market_move:
                article_score += 3
            if has_market_context and has_negative:
                article_score += 2
            if has_geopolitical and (has_market_context or has_market_move):
                article_score += 2
            if trusted and article_score > 0:
                article_score += 1

            # Political/geopolitical chatter without a market or crypto link is noise.
            if has_geopolitical and not has_market_context and not has_market_move and not has_critical:
                article_score = 0

            if article_score > 0:
                negative_count += 1
                impact_score += min(article_score, 6)
                if has_critical and (has_market_context or has_market_move or trusted):
                    critical_article_seen = True
                if len(reasons) < 3:
                    reasons.append(f"{source_name or 'unknown'}: {title[:120]}")

            positive_article_score = 0
            if has_market_context and has_positive:
                positive_article_score += 2
            if trusted and positive_article_score > 0:
                positive_article_score += 1

            if positive_article_score > 0:
                positive_count += 1
                positive_score += min(positive_article_score, 4)

        net_score = impact_score - positive_score

        if (
            net_score >= Config.NEWS_SENTIMENT_CRITICAL_THRESHOLD
            or (critical_article_seen and net_score >= Config.NEWS_SENTIMENT_BLOCK_THRESHOLD)
        ):
            return HeadlineImpact("BEARISH", negative_count, positive_count, impact_score, positive_score, "CRITICAL", reasons)

        if net_score >= Config.NEWS_SENTIMENT_BLOCK_THRESHOLD:
            return HeadlineImpact("BEARISH", negative_count, positive_count, impact_score, positive_score, "HIGH", reasons)

        if net_score >= Config.NEWS_SENTIMENT_WARN_THRESHOLD:
            return HeadlineImpact("BEARISH", negative_count, positive_count, impact_score, positive_score, "MEDIUM", reasons)

        if positive_score - impact_score >= Config.NEWS_SENTIMENT_WARN_THRESHOLD:
            return HeadlineImpact("BULLISH", negative_count, positive_count, impact_score, positive_score, "LOW", reasons)

        return HeadlineImpact("NEUTRAL", negative_count, positive_count, impact_score, positive_score, "LOW", reasons)

    def _parse_dt(self, value: str) -> Optional[datetime]:
        value = value.strip()

        try:
            if value.endswith("Z"):
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        patterns = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ]

        for pattern in patterns:
            try:
                dt = datetime.strptime(value, pattern)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

        return None
