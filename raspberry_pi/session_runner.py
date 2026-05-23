"""
=============================================================================
Session Runner - Project Spotless (Contract v1.1)
=============================================================================
Orchestrates one bath session from QR-scan to completion. Wires
StageExecutor to all the persistence layers:

  - Local SQLite (`session_progress` table) via SessionProgressStore
  - Cloud RDS (`booking_sessions` + `bookings`) via CloudSyncQueue
  - Legacy spotless session log table via db_sessions (kept for backward
    compatibility with the existing analytics queries)
  - Email notifications via EmailService
  - Geyser + Roof-light side effects via the peripheral controllers
  - SocketIO UI events via the `emit` callback

There is NO separate hardware thread — StageExecutor.run_session() is the
single, deterministic timeline that drives both relays and UI.

Two entrypoints:
    runner.start_fresh(machine_request, validation_result)
        -> for new sessions (gates 1-7 passed, no in-flight row)
    runner.start_resume(machine_request, validation_result, resume_state)
        -> for sessions that resume an in_progress booking_sessions row

The old test/service-mode codes (TEST / DEMO / DRY etc.) go through
    runner.start_test(session_type, qr_code)
which bypasses booking_sessions entirely (contract §13.0).
=============================================================================
"""

from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

import db_bookings
import db_sessions
from session_progress import SessionProgressStore
from spotless_controller import ResumeState, SessionResult

logger = logging.getLogger(__name__)


# =============================================================================
# Major stages that trigger cloud writes (contract §8.5)
# =============================================================================
MAJOR_STAGES: Set[str] = {
    "shampoo",
    "water_1",
    "conditioner",
    "water_2",
    "towel_dry",
    "dryer_phase2",
    "disinfectant",
    "disinfect_rinse",
    "flush_top",
}


EventCallback = Callable[[str, Dict[str, Any]], None]


def _noop_emit(*_args, **_kwargs) -> None:
    pass


# =============================================================================
# Runner
# =============================================================================

class SessionRunner:
    """Single-session orchestrator. Construct once per kiosk."""

    def __init__(
        self,
        executor,
        config_mgr,
        *,
        db=None,
        emit: Optional[EventCallback] = None,
        email_service=None,
        machine_id: str = "",
        geyser_controller=None,
        roof_controller=None,
        progress_store: Optional[SessionProgressStore] = None,
        cloud_sync=None,
    ):
        self.executor = executor
        self.config_mgr = config_mgr
        self.db = db
        self.emit = emit or _noop_emit
        self.email_service = email_service
        self.machine_id = machine_id
        self.geyser = geyser_controller
        self.roof = roof_controller
        self.progress_store = progress_store
        self.cloud_sync = cloud_sync

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.current_session: Optional[Dict[str, Any]] = None

    # ---------------------------------------------------------------- helpers
    @property
    def is_active(self) -> bool:
        return self._running and self.current_session is not None

    def stop(self, reason: str = "admin-stop") -> None:
        """External stop — sets the flag and asks the executor to shut down."""
        self._running = False
        if self.executor:
            try:
                self.executor.stop(reason=reason)
            except TypeError:
                self.executor.stop()
        self.emit("session_stopped", {"message": f"Session stopped: {reason}"})

    def _enqueue_cloud(self, op: str, payload: Dict[str, Any]) -> None:
        if not self.cloud_sync:
            return
        try:
            self.cloud_sync.enqueue(op, payload)
        except Exception as e:
            logger.error(f"cloud_sync.enqueue({op}) failed: {e}")

    # =========================================================================
    # Public entry: fresh booking session
    # =========================================================================

    def start_fresh(
        self,
        *,
        validation_result,                     # ValidationResult from qr_validator
        addons_raw: str = "",
    ) -> bool:
        """Start a brand-new bath session from a successful QR validation."""
        if self._running:
            logger.warning("start_fresh: session already running")
            return False
        if validation_result is None or not validation_result.ok:
            logger.error("start_fresh: validation_result is not OK")
            return False

        machine_request = validation_result.machine_request or {}
        stages: List[Dict] = list(machine_request.get("stages") or [])
        if not stages:
            logger.error("start_fresh: no stages in machine_request")
            return False

        booking_code = validation_result.booking_code or ""
        pet_name     = validation_result.pet_name
        profile      = machine_request.get("profile", "A")
        mode         = machine_request.get("mode", "FULL_SESSION")
        shampoo_pump = machine_request.get("shampoo_pump") or "p1"
        dryer_extra  = int(machine_request.get("dryer_extra_seconds") or 0)
        first_stage  = stages[0].get("name", "")

        stage_budgets = {s["name"]: int(s.get("duration", 0)) for s in stages}

        # --- Local SQLite: insert/reset row ---
        if self.progress_store:
            try:
                self.progress_store.start_fresh(
                    booking_code=booking_code,
                    machine_id=self.machine_id,
                    pet_name=pet_name,
                    profile=profile,
                    mode=mode,
                    shampoo_pump=shampoo_pump,
                    dryer_extra_seconds=dryer_extra,
                    addons_raw=addons_raw or ",".join(validation_result.addons or []),
                    stage_budgets=stage_budgets,
                    current_stage_name=first_stage,
                )
            except Exception as e:
                logger.error(f"start_fresh: progress_store.start_fresh failed: {e}")

        # --- Cloud: §8.1 insert booking_sessions row + bookings.confirmed ---
        self._enqueue_cloud("session_start", {
            "booking_code": booking_code,
            "machine_id":   self.machine_id,
            "last_stage":   first_stage,
        })

        self.current_session = {
            "kind": "booking",
            "booking_code": booking_code,
            "customer_name": validation_result.customer_name,
            "pet_name": pet_name,
            "pet_size": validation_result.pet_size,
            "package": validation_result.package,
            "addons": list(validation_result.addons or []),
            "profile": profile,
            "mode": mode,
            "shampoo_pump": shampoo_pump,
            "dryer_extra_seconds": dryer_extra,
            "stages": stages,
            "current_stage": 0,
            "stage_progress": 0,
            "started_at": datetime.now().isoformat(),
            "is_resume": False,
        }
        self._running = True
        self._thread = threading.Thread(
            target=self._run_booking,
            args=(validation_result, stages, None),
            daemon=True,
        )
        self._thread.start()
        return True

    # =========================================================================
    # Public entry: resume an in-progress booking
    # =========================================================================

    def start_resume(
        self,
        *,
        validation_result,
        resume_state: ResumeState,
        addons_raw: str = "",
    ) -> bool:
        """Resume an interrupted session for an in_progress booking."""
        if self._running:
            logger.warning("start_resume: session already running")
            return False
        if validation_result is None or not validation_result.ok:
            logger.error("start_resume: validation_result is not OK")
            return False

        machine_request = validation_result.machine_request or {}
        stages: List[Dict] = list(machine_request.get("stages") or [])
        if not stages:
            logger.error("start_resume: no stages in machine_request")
            return False

        booking_code = validation_result.booking_code or ""
        first_stage = stages[0].get("name", "")
        # Last stage that the executor will be in flight on
        resume_stage_name = (
            stages[resume_state.current_stage_idx]["name"]
            if 0 <= resume_state.current_stage_idx < len(stages)
            else first_stage
        )

        # --- Local: bump resume_count if row exists, else fresh insert as fallback ---
        if self.progress_store:
            existing = self.progress_store.load(booking_code)
            if existing is None:
                # Cold local recovery (contract §9.2 fallback): rebuild row from cloud state
                stage_budgets = {s["name"]: int(s.get("duration", 0)) for s in stages}
                self.progress_store.start_fresh(
                    booking_code=booking_code,
                    machine_id=self.machine_id,
                    pet_name=validation_result.pet_name,
                    profile=machine_request.get("profile", "A"),
                    mode=machine_request.get("mode", "FULL_SESSION"),
                    shampoo_pump=machine_request.get("shampoo_pump") or "p1",
                    dryer_extra_seconds=int(machine_request.get("dryer_extra_seconds") or 0),
                    addons_raw=addons_raw or ",".join(validation_result.addons or []),
                    stage_budgets=stage_budgets,
                    current_stage_name=resume_stage_name,
                )
                # Pre-populate completed_stages by replaying the resume_state's CSV
                for done in resume_state.completed_stages:
                    self.progress_store.complete_stage(
                        booking_code,
                        completed_stage_name=done,
                        stage_delivered={**{n: 0 for n in stage_budgets},
                                          **{done: stage_budgets.get(done, 0)}},
                        next_stage_name=resume_stage_name,
                        next_stage_idx=resume_state.current_stage_idx,
                    )
                logger.warning(
                    f"start_resume: cold local recovery for {booking_code} "
                    f"({len(resume_state.completed_stages)} stages re-applied)"
                )

            new_count = self.progress_store.increment_resume_count(booking_code)
            logger.info(f"start_resume: local resume_count={new_count}")

        # --- Cloud: §8.2 ---
        self._enqueue_cloud("session_resume", {
            "booking_code": booking_code,
            "machine_id":   self.machine_id,
            "last_stage":   resume_stage_name,
        })

        self.current_session = {
            "kind": "booking",
            "booking_code": booking_code,
            "customer_name": validation_result.customer_name,
            "pet_name": validation_result.pet_name,
            "package": validation_result.package,
            "addons": list(validation_result.addons or []),
            "stages": stages,
            "current_stage": resume_state.current_stage_idx,
            "started_at": datetime.now().isoformat(),
            "is_resume": True,
        }
        self._running = True
        self._thread = threading.Thread(
            target=self._run_booking,
            args=(validation_result, stages, resume_state),
            daemon=True,
        )
        self._thread.start()
        return True

    # =========================================================================
    # Public entry: service-mode / test session (no booking lifecycle)
    # =========================================================================

    def start_test(self, session_type: str, qr_code: str) -> bool:
        """Run a service-mode session (TEST / DEMO / DRY / WATER ...).

        These do NOT touch booking_sessions and do NOT log to cloud.
        """
        if self._running:
            logger.warning("start_test: session already running")
            return False
        from session_stages import get_stages
        stages = get_stages(session_type)
        if not stages:
            logger.error(f"start_test: unknown session_type {session_type!r}")
            return False

        self.current_session = {
            "kind": "test",
            "session_type": session_type,
            "qr_code": qr_code,
            "stages": stages,
            "current_stage": 0,
            "started_at": datetime.now().isoformat(),
        }
        self._running = True
        self._thread = threading.Thread(
            target=self._run_test,
            args=(session_type, qr_code, stages),
            daemon=True,
        )
        self._thread.start()
        return True

    # =========================================================================
    # Worker - booking session (fresh or resume)
    # =========================================================================

    def _run_booking(
        self,
        validation_result,
        stages: List[Dict],
        resume_state: Optional[ResumeState],
    ) -> None:
        booking_code = validation_result.booking_code or ""
        start_dt = datetime.now()
        db_session_id = None

        try:
            # --- Roof light ON ---
            if self.roof:
                try:
                    self.roof.on_session_start()
                except Exception as e:
                    logger.warning(f"roof.on_session_start: {e}")

            # --- Legacy spotless_sessions DB log (analytics compatibility) ---
            if self.db:
                try:
                    db_session_id = db_sessions.log_session_activated(
                        self.db,
                        booking_code,
                        self.machine_id,
                        validation_result.package or "bath_pkg",
                        booking_code,
                        None,
                    )
                    if db_session_id:
                        db_sessions.log_session_start(self.db, db_session_id)
                        db_sessions.log_session_in_progress(self.db, db_session_id)
                except Exception as e:
                    logger.warning(f"db_sessions legacy log failed: {e}")

            # --- Email: session started ---
            self._send_start_email(validation_result)

            # --- Build callbacks ---
            def on_stage_start(stage, idx):
                if self.current_session:
                    self.current_session["current_stage"] = idx

            def on_progress_flush(stage, delivered):
                if not self.progress_store:
                    return
                try:
                    # Load fresh and merge — keeps other stages' values intact.
                    sp = self.progress_store.load(booking_code)
                    if sp is None:
                        return
                    sp.stage_delivered[stage["name"]] = int(delivered)
                    self.progress_store.update_progress(
                        booking_code,
                        stage_delivered=sp.stage_delivered,
                        current_stage_name=stage["name"],
                        current_stage_idx=stage_index_of(stages, stage["name"]),
                    )
                except Exception as e:
                    logger.error(f"on_progress_flush: {e}")

            def on_stage_complete(stage, idx, delivered, is_major=True):
                """Called for EVERY stage. Local tracks all; cloud only majors."""
                # Local: bump completed_stages CSV + advance pointers
                if self.progress_store:
                    try:
                        sp = self.progress_store.load(booking_code)
                        if sp is not None:
                            sp.stage_delivered[stage["name"]] = int(delivered)
                            next_idx = idx + 1
                            next_name = (
                                stages[next_idx]["name"] if next_idx < len(stages)
                                else stage["name"]
                            )
                            self.progress_store.complete_stage(
                                booking_code,
                                completed_stage_name=stage["name"],
                                stage_delivered=sp.stage_delivered,
                                next_stage_name=next_name,
                                next_stage_idx=next_idx,
                            )
                    except Exception as e:
                        logger.error(f"on_stage_complete local: {e}")
                # Cloud: deduped append, only for major stages (contract §8.3, §8.5)
                if is_major:
                    self._enqueue_cloud("stage_complete", {
                        "booking_code": booking_code,
                        "machine_id":   self.machine_id,
                        "stage_name":   stage["name"],
                    })

            def on_session_complete(result: SessionResult):
                if self.progress_store:
                    try:
                        self.progress_store.mark_completed(booking_code)
                    except Exception as e:
                        logger.error(f"mark_completed: {e}")
                # Cloud §8.4 — also flips bookings.status='completed'
                self._enqueue_cloud("session_complete", {
                    "booking_code": booking_code,
                    "machine_id":   self.machine_id,
                })

            def on_abort(result: SessionResult):
                if self.progress_store:
                    try:
                        self.progress_store.mark_aborted(
                            booking_code, result.abort_reason or "unknown"
                        )
                    except Exception as e:
                        logger.error(f"mark_aborted: {e}")
                self._enqueue_cloud("session_abort", {
                    "booking_code": booking_code,
                    "machine_id":   self.machine_id,
                    "reason":       result.abort_reason or "unknown",
                })

            confirm_on_fn = _make_confirm_on_fn(self.executor)

            # --- Run the executor ---
            result = self.executor.run_session(
                stages,
                emit=self._emit_with_session_state,
                on_stage_start=on_stage_start,
                on_progress_flush=on_progress_flush,
                on_stage_complete=on_stage_complete,
                on_session_complete=on_session_complete,
                on_abort=on_abort,
                resume_state=resume_state,
                major_stages=MAJOR_STAGES,
                confirm_on_fn=confirm_on_fn,
            )

            total_duration = int((datetime.now() - start_dt).total_seconds())

            # --- Legacy DB rollup ---
            if self.db and db_session_id:
                try:
                    if result.aborted:
                        db_sessions.log_session_stopped(
                            self.db, db_session_id, total_duration
                        )
                    elif result.ok:
                        db_sessions.log_session_complete(
                            self.db, db_session_id, total_duration
                        )
                except Exception as e:
                    logger.warning(f"db_sessions rollup failed: {e}")

            # --- Customer-facing events ---
            if result.ok:
                self.emit("session_complete", {
                    "booking_code": booking_code,
                    "duration": total_duration,
                    "message": "Thank you for using Petgully Spotless!",
                })
                self._send_complete_email(validation_result, total_duration)
                # Geyser re-heat after session (contract: ready for next customer)
                if self.geyser:
                    try:
                        self.geyser.on_session_complete()
                    except Exception as e:
                        logger.warning(f"geyser.on_session_complete: {e}")
            else:
                self.emit("session_aborted", {
                    "booking_code": booking_code,
                    "reason": result.abort_reason or "stopped",
                    "completed_stages": result.completed_stages,
                })

            # --- Offline log mirror (existing analytics) ---
            try:
                self.config_mgr.log_session(
                    session_type=validation_result.package or "bath_pkg",
                    qr_code=booking_code,
                    start_time=start_dt,
                    end_time=datetime.now(),
                    status="completed" if result.ok else "aborted",
                )
            except Exception as e:
                logger.warning(f"config_mgr.log_session failed: {e}")

        except Exception as e:
            logger.error(f"Booking session error: {e}\n{traceback.format_exc()}")
            try:
                if self.progress_store:
                    self.progress_store.mark_aborted(booking_code, f"runner-exception:{e}")
                self._enqueue_cloud("session_abort", {
                    "booking_code": booking_code,
                    "machine_id":   self.machine_id,
                    "reason":       f"runner-exception:{e}",
                })
            except Exception:
                pass
            if self.db and db_session_id:
                try:
                    db_sessions.log_session_error(self.db, db_session_id, str(e))
                except Exception:
                    pass
            self.emit("session_error", {
                "error": str(e),
                "message": "An error occurred. Please contact management.",
            })
        finally:
            self._running = False
            self.current_session = None
            if self.roof:
                try:
                    self.roof.on_session_complete()
                except Exception:
                    pass

    # =========================================================================
    # Worker - service-mode test session
    # =========================================================================

    def _run_test(self, session_type: str, qr_code: str,
                  stages: List[Dict]) -> None:
        start_dt = datetime.now()
        try:
            if self.roof:
                try: self.roof.on_session_start()
                except Exception: pass

            confirm_on_fn = _make_confirm_on_fn(self.executor)
            result = self.executor.run_session(
                stages,
                emit=self._emit_with_session_state,
                confirm_on_fn=confirm_on_fn,
            )
            total_duration = int((datetime.now() - start_dt).total_seconds())

            if result.ok:
                self.emit("session_complete", {
                    "session_type": session_type, "qr_code": qr_code,
                    "duration": total_duration,
                    "message": "Service test complete.",
                })
            else:
                self.emit("session_aborted", {
                    "session_type": session_type, "qr_code": qr_code,
                    "reason": result.abort_reason or "stopped",
                })

            try:
                self.config_mgr.log_session(
                    session_type=session_type, qr_code=qr_code,
                    start_time=start_dt, end_time=datetime.now(),
                    status="completed" if result.ok else "aborted",
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Test session error: {e}\n{traceback.format_exc()}")
            self.emit("session_error", {"error": str(e)})
        finally:
            self._running = False
            self.current_session = None
            if self.roof:
                try: self.roof.on_session_complete()
                except Exception: pass

    # =========================================================================
    # Misc
    # =========================================================================

    def _emit_with_session_state(self, event_name: str, data: Dict) -> None:
        """Tap into emits to keep current_session.current_stage in sync."""
        if event_name == "stage_start" and self.current_session:
            self.current_session["current_stage"] = data.get("stage_index", 0)
            self.current_session["stage_progress"] = 0
        elif event_name == "stage_progress" and self.current_session:
            self.current_session["stage_progress"] = data.get("progress", 0)
        self.emit(event_name, data)

    def _send_start_email(self, vr) -> None:
        try:
            if self.email_service and hasattr(self.email_service, "send_session_start_email"):
                self.email_service.send_session_start_email(
                    session_type=vr.package or "bath_pkg",
                    qr_code=vr.booking_code,
                    machine_id=self.machine_id,
                    customer_name=vr.customer_name or "",
                    pet_name=vr.pet_name or "",
                )
        except Exception as e:
            logger.warning(f"Session-start email failed: {e}")

    def _send_complete_email(self, vr, duration: int) -> None:
        try:
            if self.email_service:
                self.email_service.send_session_email(
                    session_type=vr.package or "bath_pkg",
                    machine_id=self.machine_id,
                    qr_code=vr.booking_code,
                    duration=duration,
                )
        except Exception as e:
            logger.warning(f"Session-complete email failed: {e}")


# =============================================================================
# Helpers
# =============================================================================

def stage_index_of(stages: List[Dict], stage_name: str) -> int:
    for i, s in enumerate(stages):
        if s.get("name") == stage_name:
            return i
    return 0


def _make_confirm_on_fn(executor):
    """Return a confirm_on_fn for StageExecutor.

    Today the DeviceController doesn't expose a per-relay state cache, so we
    fall back to the optimistic policy (executor._optimistic_confirm). The
    seam is here: when MQTT state caching lands, replace this with a real
    state-reading callback.
    """
    if executor is None:
        return None
    return executor._optimistic_confirm
