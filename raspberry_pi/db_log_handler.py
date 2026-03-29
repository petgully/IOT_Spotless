"""
=============================================================================
Database Log Handler - Project Spotless
=============================================================================
Custom logging.Handler that writes Python log records to the system_logs
table in Aurora MySQL.

Uses a background thread + queue so log calls never block the main thread.
Logs are batch-inserted every FLUSH_INTERVAL seconds (or when the buffer
hits BATCH_SIZE). If the DB is unreachable, records are silently dropped
(file logging still works as the primary fallback).
=============================================================================
"""

import logging
import threading
import traceback as tb_module
from queue import Queue, Empty
from typing import Optional

logger = logging.getLogger(__name__)


FLUSH_INTERVAL = 2.0   # seconds between batch flushes
BATCH_SIZE = 50         # max records per INSERT


class DatabaseLogHandler(logging.Handler):
    """
    Logging handler that inserts records into the system_logs table.

    Usage:
        handler = DatabaseLogHandler(db_config, machine_id="BS01")
        logging.getLogger().addHandler(handler)
    """

    def __init__(self, db_config, machine_id: str = "", level=logging.INFO):
        super().__init__(level)
        self._db_config = db_config
        self._machine_id = machine_id
        self._queue: Queue = Queue()
        self._running = True
        self._connection = None

        self._worker = threading.Thread(
            target=self._flush_loop, daemon=True, name="db-log-writer"
        )
        self._worker.start()

    def set_machine_id(self, machine_id: str):
        self._machine_id = machine_id

    # ------------------------------------------------------------------
    # logging.Handler interface
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord):
        """Queue the record for async DB insertion (never blocks caller)."""
        try:
            entry = {
                "machine_id": self._machine_id,
                "log_level": record.levelname,
                "logger_name": record.name,
                "message": self.format(record),
                "source_file": record.pathname,
                "line_number": record.lineno,
                "func_name": record.funcName,
                "traceback": self._format_exception(record),
            }
            self._queue.put_nowait(entry)
        except Exception:
            self.handleError(record)

    def close(self):
        """Flush remaining records and shut down the worker thread."""
        self._running = False
        self._worker.join(timeout=5)
        self._disconnect()
        super().close()

    # ------------------------------------------------------------------
    # Background writer
    # ------------------------------------------------------------------

    def _flush_loop(self):
        """Worker thread: drain the queue in batches."""
        while self._running:
            batch = self._drain_queue(max_items=BATCH_SIZE, timeout=FLUSH_INTERVAL)
            if batch:
                self._write_batch(batch)
        # Final flush on shutdown
        batch = self._drain_queue(max_items=BATCH_SIZE * 10, timeout=0.1)
        if batch:
            self._write_batch(batch)

    def _drain_queue(self, max_items: int, timeout: float) -> list:
        """Pull up to max_items records from the queue."""
        items = []
        try:
            first = self._queue.get(timeout=timeout)
            items.append(first)
        except Empty:
            return items

        while len(items) < max_items:
            try:
                items.append(self._queue.get_nowait())
            except Empty:
                break
        return items

    def _write_batch(self, batch: list):
        """INSERT a batch of log entries into system_logs."""
        conn = self._ensure_connection()
        if not conn:
            return

        sql = """
            INSERT INTO system_logs
                (machine_id, log_level, logger_name, message,
                 source_file, line_number, func_name, traceback)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            with conn.cursor() as cursor:
                rows = [
                    (
                        e["machine_id"],
                        e["log_level"],
                        e["logger_name"],
                        e["message"][:65535],
                        (e["source_file"] or "")[:200],
                        e["line_number"],
                        (e["func_name"] or "")[:100],
                        e["traceback"],
                    )
                    for e in batch
                ]
                cursor.executemany(sql, rows)
            conn.commit()
        except Exception:
            self._disconnect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _ensure_connection(self):
        """Return an active pymysql connection, or None."""
        if self._connection:
            try:
                self._connection.ping(reconnect=False)
                return self._connection
            except Exception:
                self._disconnect()

        try:
            import pymysql
            from pymysql.cursors import DictCursor

            cfg = self._db_config
            ssl_config = {"ssl": {"ssl": True}} if getattr(cfg, "ssl_enabled", True) else {}
            self._connection = pymysql.connect(
                host=cfg.host,
                port=cfg.port,
                user=cfg.user,
                password=cfg.password,
                database=cfg.database,
                charset=getattr(cfg, "charset", "utf8mb4"),
                connect_timeout=5,
                read_timeout=5,
                write_timeout=5,
                cursorclass=DictCursor,
                autocommit=True,
                **ssl_config,
            )
            return self._connection
        except Exception:
            return None

    def _disconnect(self):
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_exception(record: logging.LogRecord) -> Optional[str]:
        if record.exc_info and record.exc_info[0] is not None:
            return "".join(tb_module.format_exception(*record.exc_info))
        return None
