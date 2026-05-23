"""
=============================================================================
Cloud Sync Queue - Project Spotless (Contract v1.1 §8.7)
=============================================================================
Best-effort cloud write retry layer for the kiosk.

The kiosk MUST NOT block on a slow / unreachable RDS — local SQLite is the
source of truth. This module:

    1. Accepts named "cloud operations" (start / resume / stage / complete / abort)
       on a thread-safe queue.
    2. Tries each one immediately via a user-supplied executor callback.
    3. On failure (RDS down / network down): persists the queue to
       data/cloud_write_queue.json and a background thread retries with
       exponential backoff.
    4. Surfaces a `is_degraded` flag + queue depth so the kiosk UI can warn
       the operator when the backlog grows beyond `queue_max_warn`.

The actual SQL is implemented in `db_bookings.py` (Phase 2.5) — this module
is transport-agnostic and only knows op names + payload dicts.
=============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Paths
# =============================================================================
DATA_DIR   = Path(__file__).resolve().parent / "data"
QUEUE_FILE = DATA_DIR / "cloud_write_queue.json"


# =============================================================================
# Operation record
# =============================================================================

# Valid operation names. The executor callback receives (op_name, payload).
VALID_OPS = {
    "session_start",       # contract §8.1
    "session_resume",      # contract §8.2
    "stage_complete",      # contract §8.3
    "session_complete",    # contract §8.4
    "session_abort",       # contract §8.6
}


@dataclass
class CloudOp:
    op: str
    payload: Dict
    op_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    next_attempt_at: float = field(default_factory=time.time)
    last_error: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "CloudOp":
        return cls(
            op             = d["op"],
            payload        = d.get("payload", {}),
            op_id          = d.get("op_id", uuid.uuid4().hex[:12]),
            created_at     = d.get("created_at", time.time()),
            attempts       = d.get("attempts", 0),
            next_attempt_at = d.get("next_attempt_at", time.time()),
            last_error     = d.get("last_error"),
        )


# =============================================================================
# Cloud sync worker
# =============================================================================

ExecutorFn = Callable[[str, Dict], None]
"""Callback signature: (op_name, payload) -> None on success, raises on failure."""


class CloudSyncQueue:
    """Background retry queue for kiosk -> RDS writes."""

    def __init__(
        self,
        executor: ExecutorFn,
        *,
        queue_file: Optional[Path] = None,
        retry_seconds: int = 30,
        queue_max_warn: int = 100,
        max_attempts: int = 0,  # 0 = retry forever (cloud writes should never be dropped)
    ):
        """
        Args:
            executor:       Callback that actually performs the cloud write.
                            Must raise on failure. Should be idempotent
                            (we retry on failure).
            queue_file:     JSON file used to persist pending ops across reboots.
            retry_seconds:  Base retry delay; backs off exponentially up to 10 min.
            queue_max_warn: Soft warning threshold for queue depth.
            max_attempts:   0 = infinite. Set >0 only for testing.
        """
        self._executor = executor
        self.queue_file = Path(queue_file) if queue_file else QUEUE_FILE
        self.retry_seconds = retry_seconds
        self.queue_max_warn = queue_max_warn
        self.max_attempts = max_attempts

        self._queue: List[CloudOp] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._degraded_logged = False

        self._ensure_dir()
        self._load_persisted()

    # ------------------------------------------------------------------ paths
    def _ensure_dir(self):
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- persistence
    def _load_persisted(self):
        if not self.queue_file.exists():
            return
        try:
            with open(self.queue_file, "r") as f:
                data = json.load(f)
            self._queue = [CloudOp.from_dict(d) for d in data]
            if self._queue:
                logger.info(
                    f"cloud_sync: loaded {len(self._queue)} pending ops from {self.queue_file}"
                )
        except Exception as e:
            logger.error(f"cloud_sync: failed to load queue file: {e}; starting empty")
            self._queue = []

    def _persist(self):
        try:
            tmp = self.queue_file.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump([op.to_dict() for op in self._queue], f, indent=2)
            os.replace(tmp, self.queue_file)
        except Exception as e:
            logger.error(f"cloud_sync: failed to persist queue: {e}")

    # ------------------------------------------------------------------ public
    def enqueue(self, op: str, payload: Dict) -> str:
        """Submit a new op. Tries immediately; falls back to retry on failure."""
        if op not in VALID_OPS:
            raise ValueError(f"cloud_sync: unknown op {op!r}")
        record = CloudOp(op=op, payload=payload)

        # Optimistic immediate attempt (non-blocking-fast).
        try:
            self._executor(op, payload)
            logger.debug(f"cloud_sync: op={op} id={record.op_id} OK (immediate)")
            return record.op_id
        except Exception as e:
            record.attempts = 1
            record.last_error = repr(e)[:200]
            record.next_attempt_at = time.time() + self._backoff(1)
            with self._lock:
                self._queue.append(record)
                depth = len(self._queue)
                self._persist()
            logger.warning(
                f"cloud_sync: op={op} id={record.op_id} immediate FAIL ({e}); "
                f"queued (depth={depth})"
            )
            if depth >= self.queue_max_warn and not self._degraded_logged:
                logger.error(
                    f"cloud_sync: DEGRADED — pending queue depth {depth} "
                    f"≥ warn threshold {self.queue_max_warn}"
                )
                self._degraded_logged = True
            self._wake.set()
            return record.op_id

    @property
    def queue_depth(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def is_degraded(self) -> bool:
        return self.queue_depth >= self.queue_max_warn

    # ------------------------------------------------------------- background
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="cloud_sync", daemon=True
        )
        self._thread.start()
        logger.info("cloud_sync: background retry thread started")

    def stop(self, timeout: float = 2.0):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self):
        while not self._stop.is_set():
            self._wake.clear()
            now = time.time()
            due: List[CloudOp] = []
            wait = self.retry_seconds
            with self._lock:
                for op in self._queue:
                    if op.next_attempt_at <= now:
                        due.append(op)
                    else:
                        wait = min(wait, op.next_attempt_at - now)

            for op in due:
                if self._stop.is_set():
                    break
                self._try_one(op)

            # Sleep until next due or the next enqueue wakes us.
            self._wake.wait(timeout=max(0.5, wait))

    def _try_one(self, op: CloudOp):
        op.attempts += 1
        try:
            self._executor(op.op, op.payload)
            with self._lock:
                if op in self._queue:
                    self._queue.remove(op)
                self._persist()
                if not self._queue and self._degraded_logged:
                    self._degraded_logged = False
                    logger.info("cloud_sync: queue drained, no longer degraded")
            logger.info(
                f"cloud_sync: op={op.op} id={op.op_id} succeeded after {op.attempts} attempts"
            )
        except Exception as e:
            op.last_error = repr(e)[:200]
            delay = self._backoff(op.attempts)
            op.next_attempt_at = time.time() + delay
            with self._lock:
                self._persist()
            logger.warning(
                f"cloud_sync: op={op.op} id={op.op_id} attempt {op.attempts} "
                f"FAIL ({e}); retry in {delay:.0f}s"
            )
            if self.max_attempts and op.attempts >= self.max_attempts:
                logger.error(
                    f"cloud_sync: op={op.op} id={op.op_id} dropped after "
                    f"{op.attempts} attempts"
                )
                with self._lock:
                    if op in self._queue:
                        self._queue.remove(op)
                    self._persist()

    def _backoff(self, attempts: int) -> float:
        """Exponential backoff capped at 10 minutes."""
        base = self.retry_seconds
        # 30s, 60s, 120s, 240s, ..., capped at 600s
        delay = min(base * (2 ** max(0, attempts - 1)), 600)
        return float(delay)
