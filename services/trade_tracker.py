import csv
import json
from datetime import datetime
from pathlib import Path

from services.stats_analyzer import StatsAnalyzer


class TradeTracker:
    def __init__(self, filepath: str = "tracked_signals.json", csv_filepath: str = "tracked_signals.csv"):
        self.path = Path(filepath)
        self.csv_path = Path(csv_filepath)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            self._save([])

        if not self.csv_path.exists():
            self._init_csv()

    def _init_csv(self):
        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "symbol",
                    "direction",
                    "entry_min",
                    "entry_max",
                    "stop_loss",
                    "tp1",
                    "tp2",
                    "tp3",
                    "score",
                    "status",
                    "realized_r",
                    "created_at",
                    "closed_at",
                    "notified",
                ],
            )
            writer.writeheader()

    def _rewrite_csv(self, data: list[dict]):
        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "symbol",
                    "direction",
                    "entry_min",
                    "entry_max",
                    "stop_loss",
                    "tp1",
                    "tp2",
                    "tp3",
                    "score",
                    "status",
                    "realized_r",
                    "created_at",
                    "closed_at",
                    "notified",
                ],
            )
            writer.writeheader()
            for row in data:
                writer.writerow(
                    {
                        "id": row.get("id"),
                        "symbol": row.get("symbol"),
                        "direction": row.get("direction"),
                        "entry_min": row.get("entry_min"),
                        "entry_max": row.get("entry_max"),
                        "stop_loss": row.get("stop_loss"),
                        "tp1": row.get("tp1"),
                        "tp2": row.get("tp2"),
                        "tp3": row.get("tp3"),
                        "score": row.get("score"),
                        "status": row.get("status"),
                        "realized_r": row.get("realized_r"),
                        "created_at": row.get("created_at"),
                        "closed_at": row.get("closed_at"),
                        "notified": row.get("notified", False),
                    }
                )

    def _load(self) -> list[dict]:
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    def _save(self, data: list[dict]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self._rewrite_csv(data)

    def _calculate_realized_r(self, item: dict, status: str) -> float:
        entry_min = float(item["entry_min"])
        entry_max = float(item["entry_max"])
        stop_loss = float(item["stop_loss"])
        tp1 = float(item["tp1"])
        tp2 = float(item["tp2"])
        tp3 = float(item["tp3"])

        entry_mid = (entry_min + entry_max) / 2.0
        direction = item["direction"]

        if direction == "LONG":
            risk = entry_mid - stop_loss
            if risk <= 0:
                return 0.0

            if status == "STOP_HIT":
                return -1.0
            if status == "TP1_HIT":
                return round((tp1 - entry_mid) / risk, 4)
            if status == "TP2_HIT":
                return round((tp2 - entry_mid) / risk, 4)
            if status == "TP3_HIT":
                return round((tp3 - entry_mid) / risk, 4)

        else:
            risk = stop_loss - entry_mid
            if risk <= 0:
                return 0.0

            if status == "STOP_HIT":
                return -1.0
            if status == "TP1_HIT":
                return round((entry_mid - tp1) / risk, 4)
            if status == "TP2_HIT":
                return round((entry_mid - tp2) / risk, 4)
            if status == "TP3_HIT":
                return round((entry_mid - tp3) / risk, 4)

        return 0.0

    def add_signal(self, payload: dict):
        data = self._load()
        payload["created_at"] = datetime.utcnow().isoformat()
        payload["status"] = "OPEN"
        payload["closed_at"] = None
        payload["realized_r"] = None
        payload["notified"] = False
        data.append(payload)
        data = data[-500:]
        self._save(data)

    def get_open_signals(self) -> list[dict]:
        data = self._load()
        return [x for x in data if x.get("status") == "OPEN"]

    def get_all_signals(self) -> list[dict]:
        return self._load()

    def update_signal(self, target_id: str, new_status: str):
        data = self._load()
        changed = False
        updated_item = None

        for item in data:
            if item.get("id") == target_id and item.get("status") == "OPEN":
                item["status"] = new_status
                item["closed_at"] = datetime.utcnow().isoformat()
                item["realized_r"] = self._calculate_realized_r(item, new_status)
                item["notified"] = False
                updated_item = item.copy()
                changed = True
                break

        if changed:
            self._save(data)

        return updated_item

    def mark_notified(self, target_id: str):
        data = self._load()
        changed = False

        for item in data:
            if item.get("id") == target_id:
                item["notified"] = True
                changed = True
                break

        if changed:
            self._save(data)

    def get_unnotified_closed_signals(self) -> list[dict]:
        data = self._load()
        return [
            x for x in data
            if x.get("status") != "OPEN" and not x.get("notified", False)
        ]

    def get_stats(self) -> dict:
        analyzer = StatsAnalyzer(self.get_all_signals())
        return analyzer.overall_stats()

    def get_pair_stats(self) -> list[dict]:
        analyzer = StatsAnalyzer(self.get_all_signals())
        return analyzer.pair_stats()

    def get_best_pairs(self, min_closed: int = 1, limit: int = 5) -> list[dict]:
        analyzer = StatsAnalyzer(self.get_all_signals())
        return analyzer.best_pairs(min_closed=min_closed, limit=limit)

    def get_side_stats(self) -> dict:
        analyzer = StatsAnalyzer(self.get_all_signals())
        return analyzer.side_stats()

    def get_daily_report(self) -> list[dict]:
        analyzer = StatsAnalyzer(self.get_all_signals())
        return analyzer.grouped_by_day()

    def get_weekly_report(self) -> list[dict]:
        analyzer = StatsAnalyzer(self.get_all_signals())
        return analyzer.grouped_by_week()

    def get_json_path(self) -> str:
        return str(self.path)

    def get_csv_path(self) -> str:
        return str(self.csv_path)