from collections import defaultdict
from datetime import datetime
from math import isfinite


def _to_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


class StatsAnalyzer:
    def __init__(self, trades: list[dict]):
        self.trades = trades

    def _closed_items(self) -> list[dict]:
        return [x for x in self.trades if x.get("status") != "OPEN"]

    def _realized_r_values(self, items: list[dict]) -> list[float]:
        values = []

        for item in items:
            if item.get("realized_r") is None:
                continue

            try:
                values.append(float(item.get("realized_r") or 0.0))
            except Exception:
                continue

        return values

    def _max_drawdown(self, items: list[dict]) -> float:
        ordered = sorted(
            [
                item
                for item in items
                if item.get("realized_r") is not None
            ],
            key=lambda x: (
                _to_datetime(x.get("closed_at"))
                or _to_datetime(x.get("created_at"))
                or datetime.min
            ),
        )

        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0

        for item in ordered:
            try:
                equity += float(item.get("realized_r") or 0.0)
            except Exception:
                continue

            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        return round(max_drawdown, 4)

    def _avg_hold_minutes(self, items: list[dict]) -> float:
        durations = []

        for item in items:
            created_at = _to_datetime(item.get("created_at"))
            closed_at = _to_datetime(item.get("closed_at"))

            if not created_at or not closed_at:
                continue

            seconds = max((closed_at - created_at).total_seconds(), 0)
            durations.append(seconds / 60.0)

        if not durations:
            return 0.0

        return round(sum(durations) / len(durations), 2)

    def equity_curve(self) -> list[dict]:
        closed_items = self._closed_items()
        ordered = sorted(
            [
                item
                for item in closed_items
                if item.get("realized_r") is not None
            ],
            key=lambda x: (
                _to_datetime(x.get("closed_at"))
                or _to_datetime(x.get("created_at"))
                or datetime.min
            ),
        )

        equity = 0.0
        rows = []

        for item in ordered:
            result_r = float(item.get("realized_r") or 0.0)
            equity += result_r
            closed_at = _to_datetime(item.get("closed_at")) or _to_datetime(item.get("created_at"))

            rows.append(
                {
                    "closed_at": closed_at.isoformat() if closed_at else "",
                    "symbol": item.get("symbol", "UNKNOWN"),
                    "result_r": round(result_r, 4),
                    "equity_r": round(equity, 4),
                }
            )

        return rows

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

        closed_items = self._closed_items()
        closed = len(closed_items)

        def is_win(item: dict) -> bool:
            if item.get("realized_r") is not None:
                return float(item.get("realized_r") or 0.0) > 0
            return item.get("status") in {"TP1_HIT", "TP2_HIT", "TP3_HIT"}

        wins = sum(1 for x in closed_items if is_win(x))
        losses = sum(1 for x in closed_items if not is_win(x))
        winrate = round((wins / closed) * 100, 2) if closed > 0 else 0.0
        stop_rate = round((stop_hit / closed) * 100, 2) if closed > 0 else 0.0

        realized_r_values = self._realized_r_values(closed_items)
        win_values = [x for x in realized_r_values if x > 0]
        loss_values = [x for x in realized_r_values if x < 0]

        total_r = round(sum(realized_r_values), 4)
        avg_r = round(total_r / closed, 4) if closed > 0 else 0.0
        expectancy = avg_r
        gross_profit = sum(win_values)
        gross_loss = abs(sum(loss_values))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        avg_win = round(sum(win_values) / len(win_values), 4) if win_values else 0.0
        avg_loss = round(sum(loss_values) / len(loss_values), 4) if loss_values else 0.0

        if isfinite(profit_factor):
            profit_factor_value = round(profit_factor, 4)
        else:
            profit_factor_value = "∞"

        return {
            "total": total,
            "open": open_count,
            "closed": closed,
            "wins": wins,
            "losses": losses,
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "tp3_hit": tp3_hit,
            "stop_hit": stop_hit,
            "stop_rate": stop_rate,
            "winrate": winrate,
            "total_r": total_r,
            "avg_r": avg_r,
            "expectancy": round(expectancy, 4),
            "profit_factor": profit_factor_value,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_drawdown": self._max_drawdown(closed_items),
            "avg_hold_minutes": self._avg_hold_minutes(closed_items),
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
                    "signals_count": stats["total"],
                    "closed_count": stats["closed"],
                    "open_count": stats["open"],
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
            created_at = _to_datetime(item.get("created_at"))
            if not created_at:
                continue

            day = created_at.date().isoformat()
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
            created_at = _to_datetime(item.get("created_at"))
            if not created_at:
                continue

            year, week, _ = created_at.isocalendar()
            iso_week = f"{year}-W{week:02d}"
            grouped[iso_week].append(item)

        rows = []
        for week, items in grouped.items():
            stats = StatsAnalyzer(items).overall_stats()
            rows.append({"week": week, **stats})

        rows.sort(key=lambda x: x["week"], reverse=True)
        return rows
