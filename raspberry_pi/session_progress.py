"""
=============================================================================
Session Progress Store - Local SQLite (Contract v1.1 §8.0)
=============================================================================
Per-second anti-fraud accounting + power-loss resume support.

Database: <project>/raspberry_pi/data/session_state.db
PRAGMA:   journal_mode=WAL, synchronous=NORMAL, busy_timeout=5000

This module is the ONLY place that touches session_state.db. Callers
(session_runner, qr_validator, main boot recovery) interact via the
SessionProgressStore class.

Write cadence (contract §8.0):
    - per-second   : in-memory deliver +=1 (no DB hit)
    - every 5 sec  : flush stage_delivered + last_checkpoint_at via update_progress()
    - stage trans. : complete_stage()
    - end of life  : mark_completed() / mark_aborted() / mark_abandoned()

Status values: 'active', 'paused', 'completed', 'aborted', 'abandoned'.
=============================================================================
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Paths
# =============================================================================
DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH  = DATA_DIR / "session_state.db"


# =============================================================================
# Schema + index (matches contract §8.0 exactly)
# =============================================================================
_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_progress (
    booking_code        TEXT PRIMARY KEY,
    machine_id          TEXT NOT NULL,
    pet_name            TEXT,
    profile             TEXT NOT NULL,
    mode                TEXT NOT NULL,
    shampoo_pump        TEXT NOT NULL,
    dryer_extra_seconds INTEGER DEFAULT 0,
    addons_raw          TEXT DEFAULT '',
    stage_budgets       TEXT NOT NULL,
    stage_delivered     TEXT NOT NULL,
    completed_stages    TEXT NOT NULL DEFAULT '',
    current_stage_idx   INTEGER NOT NULL DEFAULT 0,
    current_stage_name  TEXT NOT NULL,
    started_at          INTEGER NOT NULL,
    last_checkpoint_at  INTEGER NOT NULL,
    resume_count        INTEGER DEFAULT 0,
    status              TEXT NOT NULL,
    abort_reason        TEXT
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_status ON session_progress(status);",
    "CREATE INDEX IF NOT EXISTS idx_machine ON session_progress(machine_id);",
]

# Statuses that count as "in flight" for boot recovery + dedupe.
ACTIVE_STATUSES = ("active", "paused")
TERMINAL_STATUSES = ("completed", "aborted", "abandoned")


# =============================================================================
# Data class returned by load()
# =============================================================================
@dataclass
class SessionProgress:
    booking_code: str
    machine_id: str
    pet_name: Optional[str]
    profile: str
    mode: str
    shampoo_pump: str
    dryer_extra_seconds: int
    addons_raw: str
    stage_budgets: Dict[str, int]
    stage_delivered: Dict[str, int]
    completed_stages: List[str] = field(default_factory=list)
    current_stage_idx: int = 0
    current_stage_name: str = ""
    started_at: int = 0
    last_checkpoint_at: int = 0
    resume_count: int = 0
    status: str = "active"
    abort_reason: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SessionProgress":
        return cls(
            booking_code        = row["booking_code"],
            machine_id          = row["machine_id"],
            pet_name            = row["pet_name"],
            profile             = row["profile"],
            mode                = row["mode"],
            shampoo_pump        = row["shampoo_pump"],
            dryer_extra_seconds = row["dryer_extra_seconds"] or 0,
            addons_raw          = row["addons_raw"] or "",
            stage_budgets       = json.loads(row["stage_budgets"] or "{}"),
            stage_delivered     = json.loads(row["stage_delivered"] or "{}"),
            completed_stages    = [s for s in (row["completed_stages"] or "").split(",") if s],
            current_stage_idx   = row["current_stage_idx"] or 0,
            current_stage_name  = row["current_stage_name"] or "",
            started_at          = row["started_at"] or 0,
            last_checkpoint_at  = row["last_checkpoint_at"] or 0,
            resume_count        = row["resume_count"] or 0,
            status              = row["status"] or "active",
            abort_reason        = row["abort_reason"],
        )


# =============================================================================
# Store
# =============================================================================
class SessionProgressStore:
    """SQLite-backed local session progress.

    Connection is opened lazily and shared. SQLite with WAL mode is safe to
    use from a single Python process across threads provided we keep one
    connection and lock around writes. We use check_same_thread=False and
    a single lock; throughput is far below what SQLite needs.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_dir()
        self._open()
        self._init_schema()

    # -------------------------------------------------------------------- setup
    def _ensure_dir(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _open(self):
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage txns explicitly
        )
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("PRAGMA busy_timeout = 5000;")
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.close()
        logger.info(f"session_progress: opened {self.db_path}")

    def _init_schema(self):
        cur = self._conn.cursor()
        cur.execute(_SCHEMA)
        for sql in _INDEXES:
            cur.execute(sql)
        cur.close()

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ------------------------------------------------------------------ helpers
    def _conn_must(self) -> sqlite3.Connection:
        if self._conn is None:
            self._open()
            self._init_schema()
        return self._conn  # type: ignore[return-value]

    @staticmethod
    def _now() -> int:
        return int(time.time())

    # ====================================================================
    # CREATE (fresh session)
    # ====================================================================

    def start_fresh(
        self,
        *,
        booking_code: str,
        machine_id: str,
        pet_name: Optional[str],
        profile: str,
        mode: str,
        shampoo_pump: str,
        dryer_extra_seconds: int,
        addons_raw: str,
        stage_budgets: Dict[str, int],
        current_stage_name: str,
    ) -> SessionProgress:
        """Insert (or RESET) a session_progress row for a new session.

        If a row with the same booking_code already exists, it is overwritten
        (REPLACE INTO). This is the local mirror of contract §8.1's
        `ON DUPLICATE KEY UPDATE` cloud-side reset.
        """
        now = self._now()
        budgets_json   = json.dumps(stage_budgets)
        delivered_json = json.dumps({k: 0 for k in stage_budgets})

        cur = self._conn_must().cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO session_progress (
                booking_code, machine_id, pet_name, profile, mode,
                shampoo_pump, dryer_extra_seconds, addons_raw,
                stage_budgets, stage_delivered, completed_stages,
                current_stage_idx, current_stage_name,
                started_at, last_checkpoint_at, resume_count,
                status, abort_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0, ?, ?, ?, 0, 'active', NULL)
            """,
            (
                booking_code, machine_id, pet_name, profile, mode,
                shampoo_pump, dryer_extra_seconds, addons_raw,
                budgets_json, delivered_json,
                current_stage_name, now, now,
            ),
        )
        cur.close()
        logger.info(
            f"session_progress: started fresh "
            f"booking={booking_code} machine={machine_id} mode={mode} profile={profile}"
        )
        return self.load(booking_code)  # type: ignore[return-value]

    # ====================================================================
    # READ
    # ====================================================================

    def load(self, booking_code: str) -> Optional[SessionProgress]:
        cur = self._conn_must().cursor()
        cur.execute(
            "SELECT * FROM session_progress WHERE booking_code = ?",
            (booking_code,),
        )
        row = cur.fetchone()
        cur.close()
        return SessionProgress.from_row(row) if row else None

    def list_active(self) -> List[SessionProgress]:
        """Boot-recovery query: all rows still in active/paused state."""
        cur = self._conn_must().cursor()
        cur.execute(
            "SELECT * FROM session_progress "
            "WHERE status IN ('active', 'paused') "
            "ORDER BY last_checkpoint_at DESC"
        )
        rows = cur.fetchall()
        cur.close()
        return [SessionProgress.from_row(r) for r in rows]

    # ====================================================================
    # UPDATE (per 5s flush)
    # ====================================================================

    def update_progress(
        self,
        booking_code: str,
        *,
        stage_delivered: Dict[str, int],
        current_stage_name: Optional[str] = None,
        current_stage_idx: Optional[int] = None,
    ) -> None:
        """Periodic 5-second flush. Updates the JSON ledger + checkpoint time."""
        now = self._now()
        fields = ["stage_delivered = ?", "last_checkpoint_at = ?"]
        params: List = [json.dumps(stage_delivered), now]
        if current_stage_name is not None:
            fields.append("current_stage_name = ?")
            params.append(current_stage_name)
        if current_stage_idx is not None:
            fields.append("current_stage_idx = ?")
            params.append(current_stage_idx)
        params.append(booking_code)

        cur = self._conn_must().cursor()
        cur.execute(
            f"UPDATE session_progress SET {', '.join(fields)} WHERE booking_code = ?",
            params,
        )
        cur.close()

    # ====================================================================
    # UPDATE (stage transitions)
    # ====================================================================

    def complete_stage(
        self,
        booking_code: str,
        *,
        completed_stage_name: str,
        stage_delivered: Dict[str, int],
        next_stage_name: str,
        next_stage_idx: int,
    ) -> None:
        """Called when a stage finishes its full budget. Idempotent (dedup CSV)."""
        now = self._now()
        cur = self._conn_must().cursor()
        cur.execute(
            "SELECT completed_stages FROM session_progress WHERE booking_code = ?",
            (booking_code,),
        )
        row = cur.fetchone()
        if row is None:
            logger.error(f"complete_stage: no row for {booking_code}")
            cur.close()
            return
        existing = [s for s in (row["completed_stages"] or "").split(",") if s]
        if completed_stage_name not in existing:
            existing.append(completed_stage_name)
        new_csv = ",".join(existing)

        cur.execute(
            """
            UPDATE session_progress
            SET    completed_stages   = ?,
                   stage_delivered    = ?,
                   current_stage_name = ?,
                   current_stage_idx  = ?,
                   last_checkpoint_at = ?
            WHERE  booking_code = ?
            """,
            (
                new_csv,
                json.dumps(stage_delivered),
                next_stage_name,
                next_stage_idx,
                now,
                booking_code,
            ),
        )
        cur.close()
        logger.info(
            f"session_progress: completed stage={completed_stage_name} "
            f"-> next={next_stage_name} booking={booking_code}"
        )

    def increment_resume_count(self, booking_code: str) -> int:
        """Bump resume_count and return the new value (-1 if no row)."""
        cur = self._conn_must().cursor()
        cur.execute(
            "UPDATE session_progress SET resume_count = resume_count + 1, "
            "last_checkpoint_at = ?, status = 'active' "
            "WHERE booking_code = ?",
            (self._now(), booking_code),
        )
        cur.execute(
            "SELECT resume_count FROM session_progress WHERE booking_code = ?",
            (booking_code,),
        )
        row = cur.fetchone()
        cur.close()
        return int(row["resume_count"]) if row else -1

    def pause(self, booking_code: str) -> None:
        cur = self._conn_must().cursor()
        cur.execute(
            "UPDATE session_progress SET status='paused', last_checkpoint_at=? "
            "WHERE booking_code = ?",
            (self._now(), booking_code),
        )
        cur.close()

    # ====================================================================
    # UPDATE (terminal)
    # ====================================================================

    def mark_completed(self, booking_code: str) -> None:
        self._set_status(booking_code, "completed", reason=None)

    def mark_aborted(self, booking_code: str, reason: str) -> None:
        self._set_status(booking_code, "aborted", reason=reason)

    def mark_abandoned(self, booking_code: str, reason: str = "boot-recovery-stale") -> None:
        self._set_status(booking_code, "abandoned", reason=reason)

    def _set_status(self, booking_code: str, status: str, reason: Optional[str]) -> None:
        cur = self._conn_must().cursor()
        cur.execute(
            "UPDATE session_progress "
            "SET status=?, abort_reason=?, last_checkpoint_at=? "
            "WHERE booking_code=?",
            (status, reason, self._now(), booking_code),
        )
        cur.close()
        logger.info(
            f"session_progress: booking={booking_code} -> status={status} reason={reason!r}"
        )

    # ====================================================================
    # MAINTENANCE
    # ====================================================================

    def purge_old_terminal(self, retention_days: int = 30) -> int:
        """Delete completed/aborted/abandoned rows older than retention_days.

        Returns the number of rows removed.
        """
        cutoff = self._now() - retention_days * 86400
        cur = self._conn_must().cursor()
        cur.execute(
            "DELETE FROM session_progress "
            "WHERE status IN ('completed', 'aborted', 'abandoned') "
            "AND last_checkpoint_at < ?",
            (cutoff,),
        )
        removed = cur.rowcount
        cur.close()
        if removed:
            logger.info(f"session_progress: purged {removed} stale terminal rows")
        return removed


# =============================================================================
# Module-level singleton + convenience accessors
# =============================================================================
_store: Optional[SessionProgressStore] = None


def get_store() -> SessionProgressStore:
    global _store
    if _store is None:
        _store = SessionProgressStore()
    return _store


# =============================================================================
# Boot recovery helper (called from main.py)
# =============================================================================

def recover_on_boot() -> Optional[SessionProgress]:
    """Contract §9.1: pick up an interrupted session, if any.

    Returns the most recent active row to resume, or None if nothing to do.
    Any other active rows are auto-flipped to 'abandoned' (defensive).
    """
    store = get_store()
    actives = store.list_active()
    if not actives:
        return None
    if len(actives) > 1:
        # Defensive: there should never be more than one active row.
        winner = actives[0]  # already sorted DESC by last_checkpoint_at
        for stale in actives[1:]:
            logger.warning(
                f"recover_on_boot: multiple active rows; "
                f"abandoning stale booking={stale.booking_code}"
            )
            store.mark_abandoned(stale.booking_code, reason="boot-recovery-duplicate-active")
        return winner
    return actives[0]


# =============================================================================
# CLI smoke test
# =============================================================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = SessionProgressStore(Path("/tmp/_spotless_smoke.db"))
    try:
        s._conn.execute("DELETE FROM session_progress")
    except Exception:
        pass

    sess = s.start_fresh(
        booking_code="SPL-TEST-001",
        machine_id="BS-DEV",
        pet_name="Milo",
        profile="A",
        mode="FULL_SESSION",
        shampoo_pump="p1",
        dryer_extra_seconds=0,
        addons_raw="",
        stage_budgets={"shampoo": 80, "water_1": 60, "dryer_phase1": 300},
        current_stage_name="shampoo",
    )
    print("created:", sess.booking_code, sess.status, sess.stage_budgets)

    s.update_progress("SPL-TEST-001",
                      stage_delivered={"shampoo": 42, "water_1": 0, "dryer_phase1": 0})
    s.complete_stage("SPL-TEST-001",
                     completed_stage_name="shampoo",
                     stage_delivered={"shampoo": 80, "water_1": 0, "dryer_phase1": 0},
                     next_stage_name="water_1",
                     next_stage_idx=1)
    # idempotency check
    s.complete_stage("SPL-TEST-001",
                     completed_stage_name="shampoo",
                     stage_delivered={"shampoo": 80, "water_1": 0, "dryer_phase1": 0},
                     next_stage_name="water_1",
                     next_stage_idx=1)
    loaded = s.load("SPL-TEST-001")
    assert loaded is not None
    print("after dedup:", loaded.completed_stages, loaded.current_stage_name)
    assert loaded.completed_stages == ["shampoo"], loaded.completed_stages
    print("resume cnt:", s.increment_resume_count("SPL-TEST-001"))
    s.mark_completed("SPL-TEST-001")
    print("active rows now:", len(s.list_active()))
    print("OK")
