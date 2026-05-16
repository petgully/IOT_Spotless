"""
=============================================================================
Session Runner - Project Spotless
=============================================================================
Orchestrates a session lifecycle: DB logging, email, and calls
StageExecutor.run_session() which handles hardware + UI in one loop.

There is NO separate hardware thread — the StageExecutor countdown loop
IS both the relay timer and the UI timer.  This eliminates the old
dual-timeline drift problem.

This module owns:
    - Starting the session in a daemon thread
    - DB logging (session + stage lifecycle)
    - Email notifications (start + completion)
    - Stop / error handling
    - Geyser / roof-light lifecycle hooks

It does NOT import Flask or SocketIO.
=============================================================================
"""

import logging
import threading
import traceback
from datetime import datetime
from typing import Callable, Dict, List, Optional

import db_sessions
from db_bookings import update_booking_status

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, Dict], None]

def _noop(event_name: str, data: dict):
    pass


class SessionRunner:
    """
    Orchestrates one session from QR-scan to completion.

    Usage:
        runner = SessionRunner(executor, config_mgr, db, emit)
        runner.start("small", "QR123", session_info)
        runner.stop()
    """

    def __init__(self, executor, config_mgr,
                 db=None, emit: EventCallback = None,
                 email_service=None, machine_id: str = "",
                 geyser_controller=None, roof_controller=None):
        """
        Args:
            executor:     StageExecutor instance
            config_mgr:   ConfigManager instance
            db:           DatabaseManager (or None for offline)
            emit:         Callback(event_name, data) for UI updates
            email_service: EmailService (or None)
            machine_id:   Machine ID string
            geyser_controller:  GeyserController (or None)
            roof_controller:    RoofLightController (or None)
        """
        self.executor = executor
        self.config_mgr = config_mgr
        self.db = db
        self.emit = emit or _noop
        self.email_service = email_service
        self.machine_id = machine_id
        self.geyser = geyser_controller
        self.roof = roof_controller

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.current_session: Optional[Dict] = None

    @property
    def is_active(self) -> bool:
        return self._running and self.current_session is not None

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def start(self, session_type: str, qr_code: str,
              session_info: Dict):
        """Launch the session in a daemon thread."""
        if self._running:
            logger.warning("Session already running — ignoring start()")
            return

        stages = self.config_mgr.get_session_stages(session_type)

        self.current_session = {
            "qr_code": qr_code,
            "session_type": session_type,
            "customer_name": session_info.get("customer_name"),
            "from_database": session_info.get("from_database", False),
            "stages": stages,
            "current_stage": 0,
            "stage_progress": 0,
            "started_at": datetime.now().isoformat(),
        }
        self._running = True

        self._thread = threading.Thread(
            target=self._run,
            args=(session_type, qr_code, stages, session_info),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """Emergency-stop the running session."""
        self._running = False
        self.current_session = None
        if self.executor:
            self.executor.stop()
        self.emit("session_stopped", {"message": "Session stopped by user"})

    # -----------------------------------------------------------------
    # Internal — Main Session Thread
    # -----------------------------------------------------------------

    def _run(self, session_type: str, qr_code: str,
             stages: List[Dict], session_info: Dict):
        db = self.db
        db_session_id = None
        mobile = session_info.get("mobile_number", qr_code)
        params = session_info.get("params")
        start_time = datetime.now()

        try:
            if not self.executor:
                self.emit("session_error", {
                    "message": "System not initialized. Please restart.",
                })
                return

            # --- Roof light ON ---
            if self.roof:
                self.roof.on_session_start()

            # --- DB: session lifecycle ---
            if db:
                db_session_id = db_sessions.log_session_activated(
                    db, mobile, self.machine_id, session_type, qr_code, params)
                if db_session_id:
                    db_sessions.log_session_start(db, db_session_id)
                    db_sessions.log_session_in_progress(db, db_session_id)

            # --- Email: session started ---
            self._send_start_email(
                session_type, qr_code,
                session_info.get("customer_name", ""),
                session_info.get("pet_name", ""),
            )

            # --- Build emit wrapper that also logs to DB per-stage ---
            stage_db_ids = {}
            stage_starts = {}
            stage_order = [0]

            def emit_wrapper(event_name: str, data: dict):
                idx = data.get("stage_index", -1)
                name = data.get("stage_name", "")

                if event_name == "stage_start":
                    stage_order[0] += 1
                    if self.current_session:
                        self.current_session["current_stage"] = idx
                        self.current_session["stage_progress"] = 0
                    stage_starts[idx] = datetime.now()
                    if db and db_session_id:
                        sid = db_sessions.log_stage_start(
                            db, db_session_id, name, stage_order[0],
                            data.get("stage_duration", 0))
                        if sid:
                            stage_db_ids[idx] = sid

                elif event_name == "stage_progress":
                    if self.current_session:
                        self.current_session["stage_progress"] = data.get("progress", 0)

                elif event_name == "stage_complete":
                    if db and idx in stage_db_ids:
                        started = stage_starts.get(idx)
                        actual = int((datetime.now() - started).total_seconds()) if started else 0
                        db_sessions.log_stage_complete(db, stage_db_ids[idx], actual)

                self.emit(event_name, data)

            # --- Run all stages (single thread: relays + UI) ---
            success = self.executor.run_session(stages, emit=emit_wrapper)

            total_duration = int((datetime.now() - start_time).total_seconds())

            if not success and not self._running:
                if db and db_session_id:
                    db_sessions.log_session_stopped(db, db_session_id, total_duration)
                return

            # --- Session complete ---
            if db and db_session_id:
                db_sessions.log_session_complete(db, db_session_id, total_duration)

            booking_code = session_info.get("booking_code")
            if db and booking_code:
                update_booking_status(db, booking_code, "completed")

            self.emit("session_complete", {
                "qr_code": qr_code,
                "session_type": session_type,
                "duration": total_duration,
                "message": "Thank you for using Petgully Spotless!",
            })

            self._send_complete_email(session_type, qr_code, total_duration)

            # --- Geyser re-heat after session ---
            if self.geyser:
                self.geyser.on_session_complete()

            # --- Offline session log ---
            self.config_mgr.log_session(
                session_type=session_type,
                qr_code=qr_code,
                start_time=start_time,
                end_time=datetime.now(),
                status="completed",
            )

        except Exception as e:
            logger.error(f"Session error: {e}\n{traceback.format_exc()}")
            if db and db_session_id:
                db_sessions.log_session_error(db, db_session_id, str(e))
            self.emit("session_error", {
                "error": str(e),
                "message": "An error occurred. Please contact management.",
            })
        finally:
            self._running = False
            self.current_session = None
            if self.roof:
                self.roof.on_session_complete()

    # -----------------------------------------------------------------
    # Email Helpers
    # -----------------------------------------------------------------

    def _send_start_email(self, session_type, qr_code,
                          customer_name="", pet_name=""):
        try:
            if self.email_service and hasattr(self.email_service, "send_session_start_email"):
                self.email_service.send_session_start_email(
                    session_type=session_type,
                    qr_code=qr_code,
                    machine_id=self.machine_id,
                    customer_name=customer_name,
                    pet_name=pet_name,
                )
        except Exception as e:
            logger.warning(f"Session-start email failed: {e}")

    def _send_complete_email(self, session_type, qr_code, duration):
        try:
            if self.email_service:
                self.email_service.send_session_email(
                    session_type=session_type,
                    machine_id=self.machine_id,
                    qr_code=qr_code,
                    duration=duration,
                )
        except Exception as e:
            logger.warning(f"Email notification failed: {e}")
