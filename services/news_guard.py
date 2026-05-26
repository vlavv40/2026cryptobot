from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from config import Config


@dataclass
class NewsGuardDecision:
    blocked: bool
    reason: str
    sentiment_bias: str  # BULLISH / BEARISH / NEUTRAL
    macro_events: list[dict]
    negative_count: int
    positive_count: int


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
            )

        macro_events = await self._load_macro_events()
        macro_block_reason = self._macro_block_reason(macro_events)

        sentiment_bias = "NEUTRAL"
        negative_count = 0
        positive_count = 0

        if Config.NEWS_SENTIMENT_ENABLED:
            sentiment_bias, negative_count, positive_count = await self._load_crypto_headline_bias()

        sentiment_block_reason = None
        if (
            Config.NEWS_SENTIMENT_BLOCKS_MARKET
            and sentiment_bias == "BEARISH"
        ):
            sentiment_block_reason = (
                f"crypto news sentiment block: negative={negative_count}, "
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
                        return []
                    data = await response.json()

            if not isinstance(data, list):
                return []

            return data
        except Exception:
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

    async def _load_crypto_headline_bias(self) -> tuple[str, int, int]:
        if not self.news_api_key:
            return "NEUTRAL", 0, 0

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
                        return "NEUTRAL", 0, 0
                    data = await response.json()

            articles = data.get("articles", [])
            if not isinstance(articles, list):
                return "NEUTRAL", 0, 0

            return self._classify_headline_bias(articles)

        except Exception:
            return "NEUTRAL", 0, 0

    def _classify_headline_bias(self, articles: list[dict]) -> tuple[str, int, int]:
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

        for article in articles:
            text = (
                f"{article.get('title', '')} {article.get('description', '')}"
            ).lower()

            if any(word in text for word in negative_words):
                negative_count += 1
            if any(word in text for word in positive_words):
                positive_count += 1

        if negative_count - positive_count >= Config.NEWS_SENTIMENT_BLOCK_THRESHOLD:
            return "BEARISH", negative_count, positive_count

        if positive_count - negative_count >= Config.NEWS_SENTIMENT_BLOCK_THRESHOLD:
            return "BULLISH", negative_count, positive_count

        return "NEUTRAL", negative_count, positive_count

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
