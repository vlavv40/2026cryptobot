from datetime import datetime

from config import Config


def stats_start_at() -> datetime | None:
    value = (Config.STATS_START_DATE or "").strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def stats_period_label() -> str:
    start_at = stats_start_at()
    if not start_at:
        return "вся история"

    return f"с {start_at.strftime('%d.%m.%Y')}"
