"""File-backed circuit breaker for the recommendation-engine call.

State is persisted to a single JSON file on a volume mounted inside the pod
(`CB_STATE_PATH`, defaults to `/var/cb/state.json`). The assignment restricts us
to per-pod visibility, so a single Book-service replica + an emptyDir volume is
sufficient. A lock file guarantees read/modify/write atomicity within the pod.
"""

import json
import os
import time
from contextlib import contextmanager

try:
    import fcntl  # POSIX-only; fine for Linux containers.
except ImportError:  # pragma: no cover - Windows dev fallback
    fcntl = None


STATE_CLOSED = "closed"
STATE_OPEN = "open"


def _state_path() -> str:
    return os.getenv("CB_STATE_PATH", "/var/cb/state.json")


def _window_seconds() -> int:
    return int(os.getenv("CB_OPEN_WINDOW_SECONDS", "60"))


@contextmanager
def _locked_file(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fh = open(path, "a+")
    try:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        yield fh
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _read_state(fh) -> dict:
    raw = fh.read()
    if not raw.strip():
        return {"state": STATE_CLOSED, "opened_at": 0}
    try:
        data = json.loads(raw)
        if data.get("state") not in (STATE_CLOSED, STATE_OPEN):
            return {"state": STATE_CLOSED, "opened_at": 0}
        if "opened_at" not in data:
            data["opened_at"] = 0
        return data
    except ValueError:
        return {"state": STATE_CLOSED, "opened_at": 0}


def _write_state(fh, data: dict) -> None:
    fh.seek(0)
    fh.truncate()
    fh.write(json.dumps(data))
    fh.flush()
    try:
        os.fsync(fh.fileno())
    except OSError:
        pass


class CircuitDecision:
    """Outcome of a pre-call check."""

    __slots__ = ("allow", "trial")

    def __init__(self, allow: bool, trial: bool = False):
        self.allow = allow
        self.trial = trial


def pre_call_decision() -> CircuitDecision:
    """Decide whether to allow an outbound call.

    - closed  -> allow (not a trial)
    - open + window elapsed -> allow as trial (half-open attempt)
    - open + within window -> block
    """

    path = _state_path()
    window = _window_seconds()
    with _locked_file(path) as fh:
        data = _read_state(fh)
        if data["state"] == STATE_CLOSED:
            return CircuitDecision(allow=True, trial=False)
        elapsed = time.time() - float(data.get("opened_at", 0))
        if elapsed >= window:
            return CircuitDecision(allow=True, trial=True)
        return CircuitDecision(allow=False, trial=False)


def record_success() -> None:
    """Close the circuit (called after a successful external call)."""

    path = _state_path()
    with _locked_file(path) as fh:
        _write_state(fh, {"state": STATE_CLOSED, "opened_at": 0})


def record_failure() -> None:
    """Open the circuit (or restart the 60 s window on a failed trial)."""

    path = _state_path()
    with _locked_file(path) as fh:
        _write_state(fh, {"state": STATE_OPEN, "opened_at": time.time()})
