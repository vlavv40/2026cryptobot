from collections import defaultdict


class StatsAnalyzer:
    def __init__(self, trades: list[dict]):
        self.trades = trades

    def overall_stats(self) -> dict:
        total = len(self.trades)
        open_count = sum(1 for x in self.trades if x.get("status") == "OPEN")
        stop_hit = sum(1 for x in self.trades if x.get("status") == "STOP_HIT")
        tp1_hit = sum(1 for x in self.trades if x.get("status") == "TP1_HIT")
        tp2_hit = sum(1 for x in self.trades if x.get("status") == "TP2_HIT")
        tp3_hit = sum(1 for x in self.trades if x.get("status") == "TP3_HIT")

        closed_items = [x for x in self.trades if x.get("status") != "OPEN"]
        closed = len(closed_items)
        wins = tp1_hit + tp2_hit + tp3_hit
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

    def grouped_by_day(self) -> list[dict]:
        grouped = defaultdict(list)

        for item in self.trades:
            created_at = item.get("created_at")
            if not created_at:
                continue

            day = created_at[:10]
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
            created_at = item.get("created_at")
            if not created_at:
                continue

            week_key = created_at[:10]
            iso_week = week_key[:8]
            grouped[iso_week].append(item)

        rows = []
        for week, items in grouped.items():
            stats = StatsAnalyzer(items).overall_stats()
            rows.append({"week": week, **stats})

        rows.sort(key=lambda x: x["week"], reverse=True)
        return rows