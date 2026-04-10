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

        closed = total - open_count
        wins = tp1_hit + tp2_hit + tp3_hit
        winrate = round((wins / closed) * 100, 2) if closed > 0 else 0.0

        return {
            "total": total,
            "open": open_count,
            "closed": closed,
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "tp3_hit": tp3_hit,
            "stop_hit": stop_hit,
            "winrate": winrate,
        }

    def pair_stats(self) -> list[dict]:
        grouped = defaultdict(list)

        for trade in self.trades:
            grouped[trade.get("symbol", "UNKNOWN")].append(trade)

        rows = []
        for symbol, items in grouped.items():
            total = len(items)
            open_count = sum(1 for x in items if x.get("status") == "OPEN")
            closed = total - open_count

            tp1_hit = sum(1 for x in items if x.get("status") == "TP1_HIT")
            tp2_hit = sum(1 for x in items if x.get("status") == "TP2_HIT")
            tp3_hit = sum(1 for x in items if x.get("status") == "TP3_HIT")
            stop_hit = sum(1 for x in items if x.get("status") == "STOP_HIT")

            wins = tp1_hit + tp2_hit + tp3_hit
            winrate = round((wins / closed) * 100, 2) if closed > 0 else 0.0

            rows.append(
                {
                    "symbol": symbol,
                    "total": total,
                    "open": open_count,
                    "closed": closed,
                    "tp1_hit": tp1_hit,
                    "tp2_hit": tp2_hit,
                    "tp3_hit": tp3_hit,
                    "stop_hit": stop_hit,
                    "winrate": winrate,
                }
            )

        rows.sort(key=lambda x: (x["winrate"], x["closed"], x["total"]), reverse=True)
        return rows

    def best_pairs(self, min_closed: int = 1, limit: int = 5) -> list[dict]:
        rows = self.pair_stats()
        rows = [x for x in rows if x["closed"] >= min_closed]
        rows.sort(key=lambda x: (x["winrate"], x["closed"]), reverse=True)
        return rows[:limit]