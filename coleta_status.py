from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import Lock


_LOCK = Lock()
_STATE = {
    "enabled": False,
    "interval_seconds": 300,
    "startup_enabled": True,
    "running": False,
    "last_origin": "",
    "last_started_at": None,
    "last_finished_at": None,
    "last_success_at": None,
    "last_error": "",
    "last_result_count": None,
    "next_run_at": None,
}


def configure(enabled: bool, interval_seconds: int, startup_enabled: bool) -> None:
    with _LOCK:
        _STATE["enabled"] = enabled
        _STATE["interval_seconds"] = interval_seconds
        _STATE["startup_enabled"] = startup_enabled
        if not enabled:
            _STATE["running"] = False
            _STATE["next_run_at"] = None


def mark_started(origin: str) -> None:
    with _LOCK:
        _STATE["running"] = True
        _STATE["last_origin"] = origin
        _STATE["last_started_at"] = datetime.now()
        _STATE["last_error"] = ""


def mark_success(result_count: int) -> None:
    agora = datetime.now()
    with _LOCK:
        _STATE["running"] = False
        _STATE["last_finished_at"] = agora
        _STATE["last_success_at"] = agora
        _STATE["last_result_count"] = result_count
        _STATE["last_error"] = ""


def mark_failure(error: str) -> None:
    with _LOCK:
        _STATE["running"] = False
        _STATE["last_finished_at"] = datetime.now()
        _STATE["last_error"] = error.strip()


def set_next_run(next_run_at: datetime | None) -> None:
    with _LOCK:
        _STATE["next_run_at"] = next_run_at


def snapshot() -> dict:
    with _LOCK:
        return deepcopy(_STATE)
