import json
from datetime import datetime
from pathlib import Path


class SignalLogStore:
    def __init__(self, filepath: str = "signals_log.json"):
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
        payload["saved_at"] = datetime.utcnow().isoformat()
        data.append(payload)

        # храним последние 200 сигналов
        data = data[-200:]
        self._save(data)

    def get_last_signals(self, limit: int = 5) -> list[dict]:
        data = self._load()
        return list(reversed(data[-limit:]))