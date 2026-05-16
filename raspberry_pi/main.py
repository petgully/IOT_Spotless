#!/usr/bin/env python3
"""
=============================================================================
Project Spotless - Main Application Entry Point
=============================================================================
Raspberry Pi Master Controller

Configuration Flow:
    1. Check for Machine ID (prompt if not configured)
    2. Load configuration (Local Cache → Default)
    3. Initialize hardware controllers
    4. Start geyser pre-heat + roof light scheduler
    5. Launch kiosk web server (--kiosk mode)

Architecture:
    ConfigManager   → loads session timing configs (JSON/DB)
    DeviceController → MQTT relay control to ESP32 nodes
    GPIOController   → direct Raspberry Pi GPIO relays
    StageExecutor    → data-driven stage runner (one function for all stages)
    SessionRunner    → session lifecycle (DB logging, email, hooks)
    GeyserController → smart pre-heating with safety cutoff
    RoofLightController → session + evening schedule OR-logic

Usage:
    python main.py --kiosk              # Start with web kiosk UI
    python main.py --session small      # Run small bath from CLI
    python main.py --test               # Test all relays
    python main.py --setup              # Reset machine ID
=============================================================================
"""

import sys
import logging
import signal
import time
import argparse
from datetime import datetime

from config import NODES
from node_controller import NodeController
from device_map import DeviceController, print_device_mapping
from gpio_controller import GPIOController
from spotless_controller import StageExecutor
from config_manager import ConfigManager, get_config_manager
from session_runner import SessionRunner
from logging_config import (
    setup_logging as setup_app_logging,
    get_log_file_path,
    get_session_logger,
    set_session_logger_machine_id,
    SessionLogger,
)
from email_service import (
    EmailService,
    get_email_service,
    check_internet,
    EmailConfig,
)


class SpotlessApplication:
    """Main application class for Project Spotless."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        self.config_mgr = ConfigManager()

        # Hardware (initialized in start())
        self.controller = None      # NodeController — MQTT to ESP32s
        self.devices = None         # DeviceController — ESP32 device handles
        self.gpio = None            # GPIOController — direct Pi GPIO relays
        self.executor = None        # StageExecutor — data-driven stage runner
        self.runner = None          # SessionRunner — session lifecycle

        # Peripheral controllers
        self.geyser_ctrl = None     # GeyserController
        self.roof_ctrl = None       # RoofLightController

        # Services
        self.email_service = None
        self.session_logger = None

        self.running = False
        self._machine_id = None
        self._log_file_path = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def start(self):
        self.logger.info("=" * 60)
        self.logger.info("  Project Spotless — Starting")
        self.logger.info("=" * 60)
        self.logger.info(f"  Start Time: {datetime.now()}")

        # --- Machine ID ---
        self._machine_id = self.config_mgr.get_machine_id()
        if not self._machine_id:
            self.logger.error("Machine ID not configured. Exiting.")
            return False
        self.logger.info(f"Machine ID: {self._machine_id}")

        # --- Session logger ---
        set_session_logger_machine_id(self._machine_id)
        self.session_logger = get_session_logger(self._machine_id)
        self._log_file_path = str(get_log_file_path(self._machine_id))

        # --- Email service ---
        self.email_service = get_email_service()
        if check_internet():
            self.logger.info("Internet: CONNECTED")
        else:
            self.logger.warning("Internet: OFFLINE — emails will be skipped")

        # --- Configuration ---
        self.logger.info("--- Loading Configuration ---")
        try:
            config = self.config_mgr.load_config()
            self.logger.info(f"Config Source: {self.config_mgr.config_source.value.upper()}")
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            return False

        # --- Device mapping ---
        print_device_mapping()

        # --- GPIO controller ---
        self.logger.info("--- Initializing GPIO ---")
        self.gpio = GPIOController()
        self.gpio.print_status()

        # --- MQTT controller ---
        self.logger.info("--- Connecting to ESP32 Nodes ---")
        self.controller = NodeController()
        if not self.controller.start():
            self.logger.error("Failed to start MQTT controller")
            return False
        self.running = True

        # --- Device controller ---
        self.devices = DeviceController(self.controller)
        self.logger.info("Device controller initialized")

        # --- Stage Executor ---
        self.executor = StageExecutor(self.devices, self.gpio)
        self.logger.info("Stage executor initialized")

        # --- Geyser Controller ---
        try:
            from geyser_controller import GeyserController
            geyser_cfg = self.config_mgr.get_geyser_config()
            self.geyser_ctrl = GeyserController(self.gpio, geyser_cfg)
            self.geyser_ctrl.start()
            self.logger.info("Geyser controller started")
        except Exception as e:
            self.logger.warning(f"Geyser controller not available: {e}")

        # --- Roof Light Controller ---
        try:
            from roof_light_controller import RoofLightController
            roof_cfg = self.config_mgr.get_roof_light_config()
            self.roof_ctrl = RoofLightController(self.gpio, roof_cfg)
            self.roof_ctrl.start()
            self.logger.info("Roof light controller started")
        except Exception as e:
            self.logger.warning(f"Roof light controller not available: {e}")

        # --- Wait for nodes ---
        self.logger.info("Waiting for ESP32 nodes to connect...")
        node_status = self.controller.wait_for_nodes(timeout=30)
        for node_id, online in node_status.items():
            self.logger.info(f"  {node_id}: {'ONLINE' if online else 'OFFLINE'}")

        self.config_mgr.print_status()

        self.logger.info("=" * 60)
        self.logger.info("  System Ready")
        self.logger.info("=" * 60)
        return True

    def stop(self):
        self.logger.info("Shutting down...")
        self.running = False

        if self.geyser_ctrl:
            self.geyser_ctrl.stop()
        if self.roof_ctrl:
            self.roof_ctrl.stop()

        if self.devices:
            self.devices.all_off()
        elif self.controller:
            self.controller.all_off()

        if self.gpio:
            self.gpio.all_off()
            self.gpio.cleanup()

        if self.controller:
            self.controller.stop()

        self.logger.info("Shutdown complete")

    def all_off(self):
        self.logger.warning("ALL OFF — Emergency stop!")
        if self.executor:
            self.executor.stop()
        elif self.devices:
            self.devices.all_off()
        if self.gpio:
            self.gpio.all_off()

    # =========================================================================
    # Session API (CLI use)
    # =========================================================================

    def run_session(self, session_type: str, qr_code: str = "CLI_TEST"):
        """Run a session from the CLI (blocking)."""
        stages = self.config_mgr.get_session_stages(session_type)
        self.logger.info(f"Running {session_type}: {len(stages)} stages")

        if self.session_logger:
            self.session_logger.start_session(session_type, qr_code)

        start_time = datetime.now()

        if self.roof_ctrl:
            self.roof_ctrl.on_session_start()

        try:
            success = self.executor.run_session(stages)
            status = "completed" if success else "stopped"
        except Exception as e:
            self.logger.error(f"Session error: {e}")
            status = "error"
            success = False

        end_time = datetime.now()
        duration = int((end_time - start_time).total_seconds())

        if self.session_logger:
            self.session_logger.end_session(status)

        self.config_mgr.log_session(session_type, qr_code, start_time, end_time, status)

        if self.roof_ctrl:
            self.roof_ctrl.on_session_complete()

        if self.geyser_ctrl and success:
            self.geyser_ctrl.on_session_complete()

        if self.email_service and success:
            try:
                self.email_service.send_session_email(
                    session_type=session_type, machine_id=self._machine_id,
                    qr_code=qr_code, duration=duration,
                )
            except Exception as e:
                self.logger.warning(f"Email failed: {e}")

        return success

    def create_session_runner(self, db, emit_fn):
        """Create a SessionRunner wired to this application's components."""
        self.runner = SessionRunner(
            executor=self.executor,
            config_mgr=self.config_mgr,
            db=db,
            emit=emit_fn,
            email_service=self.email_service,
            machine_id=self._machine_id or "",
            geyser_controller=self.geyser_ctrl,
            roof_controller=self.roof_ctrl,
        )
        return self.runner

    # =========================================================================
    # Convenience methods
    # =========================================================================

    def run_test(self):
        return self.run_session("quicktest", "TEST")

    @property
    def machine_id(self) -> str:
        return self._machine_id

    def run(self):
        if not self.start():
            return 1
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
        finally:
            self.stop()
        return 0


# =============================================================================
# CLI
# =============================================================================
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Project Spotless — Pet Grooming Automation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Session Types:
  Bath:     small, large, custdiy, medsmall, medlarge, onlydisinfectant
  Utility:  quicktest, demo, onlydrying, onlywater, onlyflush,
            onlyshampoo, empty001

Examples:
    python main.py --kiosk
    python main.py --session small
    python main.py --test
    python main.py --setup
""",
    )
    parser.add_argument("--kiosk", action="store_true",
                        help="Start with web-based kiosk UI")
    parser.add_argument("--port", type=int, default=5000,
                        help="Port for kiosk web server (default: 5000)")
    parser.add_argument("--setup", action="store_true",
                        help="Run configuration setup (reset machine ID)")
    parser.add_argument("--test", action="store_true",
                        help="Run relay test mode")
    parser.add_argument("--config", action="store_true",
                        help="Print current configuration and exit")
    parser.add_argument("--list", action="store_true",
                        help="List all available session types")
    parser.add_argument("--session", type=str, metavar="TYPE",
                        help="Run a specific session type")
    parser.add_argument("--qr", type=str, default="CLI_TEST",
                        help="QR code / session identifier (default: CLI_TEST)")
    return parser.parse_args()


def main():
    args = parse_arguments()

    mgr = get_config_manager()
    machine_id = mgr.get_machine_id(prompt_if_missing=False) or ""
    setup_app_logging(machine_id=machine_id)
    logger = logging.getLogger(__name__)

    # --setup
    if args.setup:
        mgr.clear_machine_id()
        machine_id = mgr.get_machine_id()
        if machine_id:
            mgr.load_config()
            mgr.print_status()
            logger.info("Setup complete!")
        return 0

    # --list
    if args.list:
        machine_id = mgr.get_machine_id(prompt_if_missing=False)
        if machine_id:
            mgr.load_config()
        print("\n" + "=" * 60)
        print("  Available Session Types")
        print("=" * 60)
        for st in mgr.list_session_types():
            desc = mgr.get_session_description(st)
            print(f"    {st:20} {desc}")
        print("=" * 60 + "\n")
        return 0

    # --config
    if args.config:
        machine_id = mgr.get_machine_id(prompt_if_missing=False)
        if machine_id:
            mgr.load_config()
            mgr.print_status()
        else:
            logger.info("No machine configured. Run with --setup first.")
        return 0

    # Create application
    app = SpotlessApplication()

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        app.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --test
    if args.test:
        if app.start():
            app.run_test()
            app.stop()
        return 0

    # --session
    if args.session:
        if app.start():
            app.run_session(args.session, args.qr)
            app.stop()
        return 0

    # --kiosk
    if args.kiosk:
        logger.info("Starting kiosk mode...")
        if not app.start():
            logger.error("Failed to start application")
            return 1
        try:
            from kiosk.web_server import create_app, run_server
            flask_app = create_app(app)
            logger.info(f"Starting kiosk web server on port {args.port}...")
            logger.info(f"Access kiosk at: http://localhost:{args.port}")
            run_server(host="0.0.0.0", port=args.port, debug=False)
        except KeyboardInterrupt:
            logger.info("Kiosk interrupted by user")
        except Exception as e:
            logger.error(f"Kiosk error: {e}")
        finally:
            app.stop()
        return 0

    # Normal run (no kiosk)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
