from collections import defaultdict
from datetime import date, datetime


class StatsAnalyzer:
    def __init__(self, trades: list[dict]):
        self.trades = trades

    def overall_stats(self) -> dict:
        total = len(self.trades)
        open_count = sum(1 for x in self.trades if x.get("status") == "OPEN")
        stop_hit = sum(1 for x in self.trades if x.get("status") == "STOP_HIT")
        tp1_hit = sum(
            1
            for x in self.trades
            if x.get("tp1_hit_at")
            or x.get("status") in {"TP1_HIT", "TP2_HIT", "TP3_HIT"}
        )
        tp2_hit = sum(
            1
            for x in self.trades
            if x.get("tp2_hit_at")
            or x.get("status") in {"TP2_HIT", "TP3_HIT"}
        )
        tp3_hit = sum(1 for x in self.trades if x.get("status") == "TP3_HIT")

        closed_items = [x for x in self.trades if x.get("status") != "OPEN"]
        closed = len(closed_items)

        def is_win(item: dict) -> bool:
            if item.get("realized_r") is not None:
                return float(item.get("realized_r") or 0.0) > 0
            return item.get("status") in {"TP1_HIT", "TP2_HIT", "TP3_HIT"}

        wins = sum(1 for x in closed_items if is_win(x))
        winrate = round((wins / closed) * 100, 2) if closed > 0 else 0.0

        realized_r_values = [
            float(x.get("realized_r", 0.0))
            for x in closed_items
            if x.get("realized_r") is not None
        ]

        total_r = round(sum(realized_r_values), 4)
        avg_r = round(total_r / closed, 4) if closed > 0 else 0.0
        expectancy = avg_r

        return {
            "total": total,
            "open": open_count,
            "closed": closed,
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "tp3_hit": tp3_hit,
            "stop_hit": stop_hit,
            "winrate": winrate,
            "total_r": total_r,
            "avg_r": avg_r,
            "expectancy": round(expectancy, 4),
        }

    def pair_stats(self) -> list[dict]:
        grouped = defaultdict(list)

        for trade in self.trades:
            grouped[trade.get("symbol", "UNKNOWN")].append(trade)

        rows = []
        for symbol, items in grouped.items():
            stats = StatsAnalyzer(items).overall_stats()
            rows.append(
                {
                    "symbol": symbol,
                    **stats,
                }
            )

        rows.sort(
            key=lambda x: (x["expectancy"], x["winrate"], x["closed"], x["total_r"]),
            reverse=True,
        )
        return rows

    def best_pairs(self, min_closed: int = 1, limit: int = 5) -> list[dict]:
        rows = self.pair_stats()
        rows = [x for x in rows if x["closed"] >= min_closed]
        rows.sort(
            key=lambda x: (x["expectancy"], x["winrate"], x["closed"]),
            reverse=True,
        )
        return rows[:limit]

    def side_stats(self) -> dict:
        def build(direction: str) -> dict:
            filtered = [x for x in self.trades if x.get("direction") == direction]
            return StatsAnalyzer(filtered).overall_stats()

        return {
            "LONG": build("LONG"),
            "SHORT": build("SHORT"),
        }

    def _to_date(self, value) -> date | None:
        if not value:
            return None

        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except ValueError:
            return None

    def grouped_by_day(self) -> list[dict]:
        grouped = defaultdict(list)

        for item in self.trades:
            created_date = self._to_date(item.get("created_at"))
            if not created_date:
                continue
            day = created_date.isoformat()
            grouped[day].append(item)

        rows = []
        for day, items in grouped.items():
            stats = StatsAnalyzer(items).overall_stats()
            rows.append({"day": day, **stats})

        rows.sort(key=lambda x: x["day"], reverse=True)
        return rows

    def grouped_by_week(self) -> list[dict]:
        grouped = defaultdict(list)

        for item in self.trades:
            created_date = self._to_date(item.get("created_at"))
            if not created_date:
                continue

            iso = created_date.isocalendar()
            iso_week = f"{iso.year}-W{iso.week:02d}"
            grouped[iso_week].append(item)

        rows = []
        for week, items in grouped.items():
            stats = StatsAnalyzer(items).overall_stats()
            rows.append({"week": week, **stats})

        rows.sort(key=lambda x: x["week"], reverse=True)
        return rows
