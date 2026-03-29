"""
=============================================================================
Session Runner - Project Spotless
=============================================================================
Runs a bath session in a background thread, emitting progress events via
a callback interface so the caller (web_server, CLI, tests) can choose
how to surface them.

This module owns:
    - Starting the hardware session thread
    - Ticking through UI stages and emitting progress every second
    - Logging session/stage lifecycle to the database
    - Sending the completion email
    - Handling stop / error states

It does NOT import Flask or SocketIO.
=============================================================================
"""

import time
import logging
import threading
import traceback
from datetime import datetime
from typing import Callable, Dict, Optional

import db_sessions
from db_bookings import update_booking_status

logger = logging.getLogger(__name__)


# Type alias for the event callback.
# Signature:  callback(event_name: str, data: dict) -> None
EventCallback = Callable[[str, Dict], None]


def _noop_callback(event_name: str, data: dict):
    """Default no-op callback when no UI is attached."""
    pass


class SessionRunner:
    """
    Orchestrates one session from QR-scan to completion.

    Usage:
        runner = SessionRunner(spotless_app, db, emit_fn)
        runner.start(session_type, qr_code, stages, session_info)
        runner.stop()   # emergency stop
    """

    def __init__(self, spotless_app, db=None,
                 emit: EventCallback = None):
        """
        Args:
            spotless_app: SpotlessApplication instance (runs hardware).
            db:           DatabaseManager instance (or None for offline).
            emit:         Callback(event_name, data) for UI updates.
        """
        self.app = spotless_app
        self.db = db
        self.emit = emit or _noop_callback

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
              stages: list, session_info: Dict):
        """Launch the session in a daemon thread."""
        if self._running:
            logger.warning("Session already running — ignoring start()")
            return

        self.current_session = {
            'qr_code': qr_code,
            'session_type': session_type,
            'customer_name': session_info.get('customer_name'),
            'from_database': session_info.get('from_database', False),
            'params': session_info.get('params'),
            'stages': stages,
            'current_stage': 0,
            'stage_progress': 0,
            'started_at': datetime.now().isoformat(),
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
        if self.app:
            self.app.all_off()
        self.emit('session_stopped', {'message': 'Session stopped by user'})

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _run(self, session_type: str, qr_code: str,
             stages: list, session_info: Dict):
        """Main loop — runs in its own thread."""
        db = self.db
        db_session_id = None
        machine_id = self.app.machine_id if self.app else 'UNKNOWN'
        params = session_info.get('params')
        mobile = session_info.get('mobile_number', qr_code)
        start_time = datetime.now()

        try:
            if not self.app:
                self.emit('session_error', {
                    'message': 'System not initialized. Please restart.'
                })
                return

            # -- DB: session activated / started / in_progress --
            if db:
                db_session_id = db_sessions.log_session_activated(
                    db, mobile, machine_id, session_type, qr_code, params)
                if db_session_id:
                    db_sessions.log_session_start(db, db_session_id)
                    db_sessions.log_session_in_progress(db, db_session_id)

            # -- Email: session started notification --
            self._send_start_email(
                session_type, machine_id, qr_code,
                session_info.get('customer_name', ''),
                session_info.get('pet_name', ''),
            )

            # -- Hardware thread --
            hw_thread = threading.Thread(
                target=self._run_hardware,
                args=(session_type, qr_code),
                daemon=True,
            )
            hw_thread.start()

            # -- Stage progress loop --
            total_stages = len(stages)
            stage_order = 0

            for i, stage in enumerate(stages):
                if not self._running:
                    if db and db_session_id:
                        dur = int((datetime.now() - start_time).total_seconds())
                        db_sessions.log_session_stopped(db, db_session_id, dur)
                    return

                stage_name = stage['name']
                stage_label = stage['label']
                stage_duration = stage['duration']
                stage_image = stage['image']
                stage_order += 1

                self.current_session['current_stage'] = i
                self.current_session['stage_progress'] = 0

                db_stage_id = None
                if db and db_session_id:
                    db_stage_id = db_sessions.log_stage_start(
                        db, db_session_id, stage_name, stage_order, stage_duration)

                stage_start = datetime.now()

                self.emit('stage_start', {
                    'stage_index': i,
                    'stage_name': stage_name,
                    'stage_label': stage_label,
                    'stage_duration': stage_duration,
                    'stage_image': stage_image,
                    'total_stages': total_stages,
                })

                for second in range(stage_duration):
                    if not self._running:
                        if db and db_stage_id:
                            db_sessions.log_stage_error(
                                db, db_stage_id, "Session stopped by user")
                        return

                    progress = int((second + 1) / stage_duration * 100)
                    remaining = stage_duration - second - 1
                    self.current_session['stage_progress'] = progress

                    self.emit('stage_progress', {
                        'stage_index': i,
                        'stage_name': stage_name,
                        'progress': progress,
                        'elapsed': second + 1,
                        'remaining': remaining,
                        'total_duration': stage_duration,
                    })
                    time.sleep(1)

                if db and db_stage_id:
                    actual = int((datetime.now() - stage_start).total_seconds())
                    db_sessions.log_stage_complete(db, db_stage_id, actual)

                self.emit('stage_complete', {
                    'stage_index': i,
                    'stage_name': stage_name,
                })

            # -- Completed --
            total_duration = int((datetime.now() - start_time).total_seconds())

            if db and db_session_id:
                db_sessions.log_session_complete(db, db_session_id, total_duration)

            booking_code = session_info.get('booking_code')
            if db and booking_code:
                update_booking_status(db, booking_code, 'completed')

            self.emit('session_complete', {
                'qr_code': qr_code,
                'session_type': session_type,
                'duration': total_duration,
                'message': 'Thank you for using Petgully Spotless!',
            })

            self._send_email(session_type, machine_id, qr_code, total_duration)

        except Exception as e:
            logger.error(f"Session error: {e}\n{traceback.format_exc()}")
            if db and db_session_id:
                db_sessions.log_session_error(db, db_session_id, str(e))
            self.emit('session_error', {
                'error': str(e),
                'message': 'An error occurred. Please contact management.',
            })
        finally:
            self._running = False
            self.current_session = None

    def _run_hardware(self, session_type: str, qr_code: str):
        """Runs the actual relay-control session in its own thread."""
        try:
            logger.info(f"Hardware session starting: {session_type} / {qr_code}")
            result = self.app.run_session(session_type, qr_code)
            logger.info(f"Hardware session finished: {session_type}, result={result}")
        except Exception as e:
            logger.error(f"Hardware session FAILED: {e}\n{traceback.format_exc()}")

    def _send_start_email(self, session_type, machine_id, qr_code,
                          customer_name='', pet_name=''):
        """Send a 'session started' email if the service is available."""
        try:
            if (self.app and hasattr(self.app, 'email_service')
                    and self.app.email_service
                    and hasattr(self.app.email_service, 'send_session_start_email')):
                self.app.email_service.send_session_start_email(
                    session_type=session_type,
                    qr_code=qr_code,
                    machine_id=machine_id,
                    customer_name=customer_name,
                    pet_name=pet_name,
                )
        except Exception as e:
            logger.warning(f"Session-start email failed: {e}")

    def _send_email(self, session_type, machine_id, qr_code, duration):
        """Send completion email if the service is available."""
        try:
            if self.app and hasattr(self.app, 'email_service') and self.app.email_service:
                self.app.email_service.send_session_email(
                    session_type=session_type,
                    machine_id=machine_id,
                    qr_code=qr_code,
                    duration=duration,
                )
        except Exception as e:
            logger.warning(f"Email notification failed: {e}")
