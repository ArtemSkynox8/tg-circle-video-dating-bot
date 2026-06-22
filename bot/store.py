from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import config

StoreMutator = Callable[[dict[str, Any]], Any]

INITIAL_STATE: dict[str, Any] = {
    "users": {},
    "events": [],
}

_lock = asyncio.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_state(data: dict[str, Any] | None) -> dict[str, Any]:
    state = data or {}
    state.setdefault("users", {})
    state.setdefault("events", [])
    return state


async def ensure_file() -> Path:
    file_path = config.data_file.resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if not file_path.exists():
        file_path.write_text(json.dumps(INITIAL_STATE, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path


async def read_store() -> dict[str, Any]:
    file_path = await ensure_file()
    raw = file_path.read_text(encoding="utf-8")
    return normalize_state(json.loads(raw))


async def write_store(data: dict[str, Any]) -> None:
    file_path = await ensure_file()
    file_path.write_text(json.dumps(normalize_state(data), ensure_ascii=False, indent=2), encoding="utf-8")


async def update_store(mutator: StoreMutator) -> Any:
    async with _lock:
        data = await read_store()
        result = mutator(data)
        await write_store(data)
        return result


async def get_user(user_id: int | str) -> dict[str, Any] | None:
    data = await read_store()
    user = data["users"].get(str(user_id))
    return deepcopy(user) if user else None


async def upsert_user(user_id: int | str, patch: dict[str, Any] | None = None) -> dict[str, Any]:
    patch = patch or {}
    user_key = str(user_id)
    now = utc_now()

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        current = data["users"].get(user_key, {})
        user = {
            "platform": "discord",
            "user_id": user_key,
            "step": "new",
            "is_paid": False,
            "answers_done": 0,
            "chat_history": [],
            "created_at": now,
            "last_message_at": now,
            **current,
            **patch,
            "updated_at": now,
        }
        data["users"][user_key] = user
        return deepcopy(user)

    return await update_store(mutate)


async def add_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    payload = payload or {}

    def mutate(data: dict[str, Any]) -> None:
        data["events"].append({"type": event_type, **payload, "created_at": utc_now()})
        data["events"] = data["events"][-1000:]

    await update_store(mutate)
