import json
from datetime import datetime, timedelta
from pathlib import Path


class StateStore:
    def __init__(self, filepath: str):
        self.path = Path(filepath)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.state = {
            "cooldowns": {},
            "last_signals": {},
        }
        self.load()

    def load(self):
        if not self.path.exists():
            self.save()
            return

        try:
            with self.path.open("r", encoding="utf-8") as f:
                self.state = json.load(f)
        except Exception:
            self.state = {
                "cooldowns": {},
                "last_signals": {},
            }
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _cleanup_expired_cooldowns(self):
        now = datetime.utcnow()
        cooldowns = self.state.get("cooldowns", {})
        alive = {}

        for key, iso_time in cooldowns.items():
            try:
                expires_at = datetime.fromisoformat(iso_time)
                if expires_at > now:
                    alive[key] = iso_time
            except Exception:
                continue

        self.state["cooldowns"] = alive
        self.save()

    def get_cooldown(self, key: str):
        self._cleanup_expired_cooldowns()
        return self.state.get("cooldowns", {}).get(key)

    def set_cooldown(self, key: str, minutes: int):
        expires_at = datetime.utcnow() + timedelta(minutes=minutes)
        self.state.setdefault("cooldowns", {})[key] = expires_at.isoformat()
        self.save()

    def get_last_signal(self, key: str):
        return self.state.get("last_signals", {}).get(key)

    def set_last_signal(self, key: str, payload: dict):
        self.state.setdefault("last_signals", {})[key] = payload
        self.save()