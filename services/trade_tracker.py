import json
from datetime import datetime
from pathlib import Path


class TradeTracker:
    def __init__(self, filepath: str = "tracked_signals.json"):
        self.path = Path(filepath)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            self._save([])

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

    def add_signal(self, payload: dict):
        data = self._load()
        payload["created_at"] = datetime.utcnow().isoformat()
        payload["status"] = "OPEN"
        payload["closed_at"] = None
        data.append(payload)
        data = data[-300:]
        self._save(data)

    def get_open_signals(self) -> list[dict]:
        data = self._load()
        return [x for x in data if x.get("status") == "OPEN"]

    def get_all_signals(self) -> list[dict]:
        return self._load()

    def update_signal(self, target_id: str, new_status: str):
        data = self._load()
        changed = False

        for item in data:
            if item.get("id") == target_id and item.get("status") == "OPEN":
                item["status"] = new_status
                item["closed_at"] = datetime.utcnow().isoformat()
                changed = True
                break

        if changed:
            self._save(data)

    def get_stats(self) -> dict:
        data = self._load()

        total = len(data)
        open_count = sum(1 for x in data if x.get("status") == "OPEN")
        stop_hit = sum(1 for x in data if x.get("status") == "STOP_HIT")
        tp1_hit = sum(1 for x in data if x.get("status") == "TP1_HIT")
        tp2_hit = sum(1 for x in data if x.get("status") == "TP2_HIT")
        tp3_hit = sum(1 for x in data if x.get("status") == "TP3_HIT")

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