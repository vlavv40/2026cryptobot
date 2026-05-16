import math
from datetime import date, datetime
from typing import Any

import aiohttp

from config import Config
from services.db import db
from utils.logger import setup_logger


logger = setup_logger()


def _enabled() -> bool:
    return bool(Config.CRYPTO_PULSE_URL and Config.BOT_INGEST_SECRET)


def _api_url(path: str) -> str:
    return f"{Config.CRYPTO_PULSE_URL.rstrip('/')}{path}"


def _get(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, dict) and name in source:
            return source[name]
        if hasattr(source, name):
            return getattr(source, name)
    return default


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]

    try:
        as_float = float(value)
        return as_float if math.isfinite(as_float) else None
    except (TypeError, ValueError):
        return str(value)


def _map_signal(signal: Any) -> dict:
    entry = _get(signal, "entry", default=None)
    entry_min = _get(signal, "entry_min", default=None)
    entry_max = _get(signal, "entry_max", default=None)

    if entry is None and entry_min is not None and entry_max is not None:
        entry = (float(entry_min) + float(entry_max)) / 2.0

    reasons = _get(signal, "reasons", default=[])
    reason = _get(signal, "reason", default=None)
    if reason is None and reasons:
        reason = "; ".join(str(item) for item in reasons)

    diagnostics = _get(signal, "diagnostics", "indicators_json", default={})
    strategy = _get(signal, "signal_type", "strategy", default=None)

    return _json_safe({
        "id": _get(signal, "id", default=None),
        "source": "bot",
        "symbol": _get(signal, "symbol", default=None),
        "direction": _get(signal, "direction", default=None),
        "entry": entry,
        "entry_min": entry_min,
        "entry_max": entry_max,
        "stop_loss": _get(signal, "stop_loss", default=None),
        "tp1": _get(signal, "tp1", default=None),
        "tp2": _get(signal, "tp2", default=None),
        "tp3": _get(signal, "tp3", default=None),
        "score": _get(signal, "score", default=None),
        "confidence": _get(signal, "confidence", "score", default=None),
        "reasons": reasons,
        "reason": reason,
        "signal_type": strategy,
        "strategy": strategy,
        "diagnostics": diagnostics,
        "indicators_json": diagnostics,
    })


async def _read_response(response: aiohttp.ClientResponse) -> Any:
    text = await response.text()
    if not text:
        return None

    try:
        return await response.json(content_type=None)
    except Exception:
        return text


async def log_bot(
    level: str,
    symbol: str | None,
    action: str,
    message: str,
    reason: str | None = None,
):
    try:
        if db.pool is None:
            return

        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_logs (level, symbol, action, message, reason)
                VALUES ($1, $2, $3, $4, $5)
                """,
                level,
                symbol,
                action,
                message,
                reason,
            )
    except Exception as error:
        logger.exception(f"[PULSE LOG ERROR] {symbol} {action} | {error}")


async def send_signal(signal: Any):
    if not _enabled():
        return None

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.post(
                _api_url("/api/bot/signals"),
                json=_map_signal(signal),
                headers={"x-bot-secret": Config.BOT_INGEST_SECRET},
            ) as response:
                if response.status >= 400:
                    body = await response.text()
                    logger.warning(
                        f"[PULSE SEND ERROR] status={response.status} body={body[:500]}"
                    )
                    return None

                return await _read_response(response)
    except Exception as error:
        logger.exception(f"[PULSE SEND ERROR] {error}")
        return None


async def update_signal(
    signal_id: str,
    status: str,
    current_price: float | None = None,
    realized_r: float | None = None,
    reason: str | None = None,
):
    if not _enabled():
        return None

    payload = {
        "status": status,
        "current_price": current_price,
        "realized_r": realized_r,
        "reason": reason,
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.patch(
                _api_url(f"/api/bot/signals/{signal_id}"),
                json=_json_safe(payload),
                headers={"x-bot-secret": Config.BOT_INGEST_SECRET},
            ) as response:
                if response.status >= 400:
                    body = await response.text()
                    logger.warning(
                        f"[PULSE UPDATE ERROR] id={signal_id} status={response.status} body={body[:500]}"
                    )
                    return None

                return await _read_response(response)
    except Exception as error:
        logger.exception(f"[PULSE UPDATE ERROR] id={signal_id} | {error}")
        return None
