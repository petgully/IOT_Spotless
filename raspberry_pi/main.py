#!/usr/bin/env python3
"""
=============================================================================
Project Spotless - Main Application Entry Point
=============================================================================
Raspberry Pi Master Controller

This is the main entry point for the Spotless system.
Run this script to start the master controller.

Configuration Flow:
    1. Check for Machine ID (prompt if not configured)
    2. Load configuration (Database → Local Cache → Default)
    3. Initialize hardware controllers
    4. Ready for bath sessions

Device Variable Names (ESP32 Nodes via MQTT):
    NODE 1: p1, p2, ro1, ro2, d1, p3, pump
    NODE 2: p4, p5, ro3, ro4, d2, s7, s9
    NODE 3: s1, s2, s3, s4, s5, s6, s8

Variable Mapping (Legacy → New):
    top → s6, bottom → s7, flushmain → s8, roof → s9

Direct GPIO Relays (Raspberry Pi):
    dry - GPIO 14, geyser - GPIO 18

Usage:
    python main.py
    python main.py --setup     # Run configuration setup
    python main.py --test      # Run relay test
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
from spotless_functions import SpotlessController
from config_manager import ConfigManager, get_config_manager
from logging_config import (
    setup_logging as setup_app_logging,
    get_log_file_path,
    get_session_logger,
    set_session_logger_machine_id,
    SessionLogger
)
from email_service import (
    EmailService,
    get_email_service,
    check_internet,
    EmailConfig
)


# =============================================================================
# Main Application
# =============================================================================
class SpotlessApplication:
    """Main application class for Project Spotless."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Configuration manager (handles machine ID and session configs)
        self.config_mgr = ConfigManager()
        
        # Hardware controllers (initialized in start())
        self.controller = None       # NodeController - MQTT to ESP32s
        self.devices = None          # DeviceController - ESP32 device handles
        self.gpio = None             # GPIOController - direct Pi GPIO relays
        self.spotless = None         # SpotlessController - bath functions
        
        # Email and logging services
        self.email_service = None    # EmailService - session notifications
        self.session_logger = None   # SessionLogger - structured session logging
        
        self.running = False
        self._machine_id = None
        self._log_file_path = None
        
    def start(self):
        """Start the application."""
        self.logger.info("=" * 60)
        self.logger.info("  Project Spotless - Starting")
        self.logger.info("=" * 60)
        self.logger.info(f"  Start Time: {datetime.now()}")
        
        # Step 1: Get Machine ID
        self.logger.info("\n--- Machine Configuration ---")
        self._machine_id = self.config_mgr.get_machine_id()
        
        if not self._machine_id:
            self.logger.error("Machine ID not configured. Exiting.")
            return False
            
        self.logger.info(f"Machine ID: {self._machine_id}")
        
        # Step 1b: Setup session logger with machine ID
        set_session_logger_machine_id(self._machine_id)
        self.session_logger = get_session_logger(self._machine_id)
        self._log_file_path = str(get_log_file_path(self._machine_id))
        
        # Step 1c: Initialize email service
        self.email_service = get_email_service()
        if check_internet():
            self.logger.info("Internet: CONNECTED")
            # Optionally send startup notification
            # self.email_service.send_startup_notification(self._machine_id)
        else:
            self.logger.warning("Internet: OFFLINE - Emails will be skipped")
        
        # Step 2: Load Configuration
        self.logger.info("\n--- Loading Configuration ---")
        try:
            config = self.config_mgr.load_config()
            self.logger.info(f"Config Source: {self.config_mgr.config_source.value.upper()}")
            self.logger.info(f"Machine Name: {config.machine_name}")
            self.logger.info(f"Location: {config.location}")
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            return False
            
        # Step 3: Print device mapping
        print_device_mapping()
        
        # Step 4: Initialize GPIO controller (direct Raspberry Pi relays)
        self.logger.info("\n--- Initializing GPIO ---")
        self.gpio = GPIOController()
        self.gpio.print_status()
        
        # Step 5: Start the MQTT controller
        self.logger.info("\n--- Connecting to ESP32 Nodes ---")
        self.controller = NodeController()
        
        if not self.controller.start():
            self.logger.error("Failed to start MQTT controller")
            return False
            
        self.running = True
        
        # Step 6: Initialize device controller (ESP32 nodes via MQTT)
        self.devices = DeviceController(self.controller)
        self.logger.info("Device controller initialized")
        
        # Step 7: Initialize Spotless controller (bath functions)
        self.spotless = SpotlessController(self.devices, self.gpio)
        self.logger.info("Spotless controller initialized")
        
        # Step 8: Wait for nodes to come online
        self.logger.info("Waiting for ESP32 nodes to connect...")
        node_status = self.controller.wait_for_nodes(timeout=30)
        
        for node_id, online in node_status.items():
            status = "ONLINE" if online else "OFFLINE"
            self.logger.info(f"  {node_id}: {status}")
            
        # Print configuration status
        self.config_mgr.print_status()
        
        self.logger.info("=" * 60)
        self.logger.info("  System Ready")
        self.logger.info("=" * 60)
        
        return True
        
    def stop(self):
        """Stop the application."""
        self.logger.info("Shutting down...")
        self.running = False
        
        # Safety: Turn off all ESP32 relays
        if self.devices:
            self.devices.all_off()
        elif self.controller:
            self.controller.all_off()
            
        # Safety: Turn off all GPIO relays
        if self.gpio:
            self.gpio.all_off()
            self.gpio.cleanup()
        
        # Stop the MQTT controller
        if self.controller:
            self.controller.stop()
        
        self.logger.info("Shutdown complete")
        
    def all_off(self):
        """Turn off ALL relays (both ESP32 and GPIO)."""
        self.logger.warning("ALL OFF - Emergency stop!")
        
        if self.devices:
            self.devices.all_off()
        if self.gpio:
            self.gpio.all_off()
            
    # =========================================================================
    # Session Control Methods
    # =========================================================================
    
    def run_session(self, session_type: str, qr_return: str = "manual"):
        """
        Run any session (bath or utility) using configuration from ConfigManager.
        
        Args:
            session_type: One of 'small', 'large', 'quicktest', 'onlywater', etc.
            qr_return: QR code/session identifier
        """
        # Check if it's a utility session
        if self.config_mgr.is_utility_session(session_type):
            return self._run_utility_session(session_type, qr_return)
        else:
            return self._run_bath_session(session_type, qr_return)
            
    def _run_bath_session(self, session_type: str, qr_return: str) -> bool:
        """
        Run a full bath session (Spotless, fromDisinfectant).
        
        Args:
            session_type: One of 'small', 'large', 'custdiy', etc.
            qr_return: QR code/session identifier
        """
        session_config = self.config_mgr.get_session_config(session_type)
        
        if not session_config:
            self.logger.error(f"Unknown session type: {session_type}")
            available = self.config_mgr.list_session_types()
            self.logger.info(f"Available bath types: {available}")
            return False
            
        params = session_config.get_params()
        handler = session_config.handler
        
        # Start session logging
        if self.session_logger:
            self.session_logger.start_session(session_type, qr_return)
            self.session_logger.log_params(**params)
        
        self.logger.info(f"Starting {session_type} bath session for {qr_return}")
        self.logger.info(f"Handler: {handler}, Parameters: {params}")
        
        # Log session start
        start_time = datetime.now()
        duration_seconds = 0
        
        try:
            # Call the appropriate handler
            if handler == "Spotless":
                self.spotless.Spotless(qr_return, **params)
            elif handler == "fromDisinfectant":
                self.spotless.fromDisinfectant(qr_return, **params)
            else:
                self.logger.error(f"Unknown handler: {handler}")
                if self.session_logger:
                    self.session_logger.log_error(f"Unknown handler: {handler}")
                    self.session_logger.end_session("error")
                return False
            status = "completed"
        except Exception as e:
            self.logger.error(f"Session error: {e}")
            if self.session_logger:
                self.session_logger.log_error(str(e))
            status = "error"
            
        # Log session end
        end_time = datetime.now()
        duration_seconds = int((end_time - start_time).total_seconds())
        
        # End session logging
        if self.session_logger:
            self.session_logger.end_session(status)
        
        # Save session log (offline storage)
        self.config_mgr.log_session(
            session_type=session_type,
            qr_code=qr_return,
            start_time=start_time,
            end_time=end_time,
            status=status
        )
        
        # Send email notification
        if self.email_service and status == "completed":
            self.email_service.send_session_email(
                session_type=session_type,
                qr_code=qr_return,
                machine_id=self._machine_id,
                duration_seconds=duration_seconds,
                log_file_path=self._log_file_path
            )
        
        return status == "completed"
        
    def _run_utility_session(self, session_type: str, qr_return: str = "manual") -> bool:
        """
        Run a utility session (test_relays, Dryer, Flush, etc.).
        
        Args:
            session_type: One of 'quicktest', 'onlydrying', 'onlywater', etc.
            qr_return: QR code/session identifier (if needed)
        """
        utility_config = self.config_mgr.get_utility_config(session_type)
        
        if not utility_config:
            self.logger.error(f"Unknown utility type: {session_type}")
            available = self.config_mgr.list_utility_types()
            self.logger.info(f"Available utility types: {available}")
            return False
            
        handler = utility_config.handler
        duration = utility_config.duration
        needs_qr = utility_config.needs_qr
        
        # Start session logging
        if self.session_logger:
            self.session_logger.start_session(session_type, qr_return)
            self.session_logger.log_params(handler=handler, duration=duration)
        
        self.logger.info(f"Starting utility: {session_type} ({utility_config.description})")
        self.logger.info(f"Handler: {handler}, Duration: {duration}s, Needs QR: {needs_qr}")
        
        # Log session start
        start_time = datetime.now()
        
        try:
            # Map handler names to SpotlessController methods
            if handler == "test_relays":
                self.spotless.test_relays()
            elif handler == "demo":
                self.spotless.demo(qr_return)
            elif handler == "Dryer":
                self.spotless.Dryer(qr_return, duration)
            elif handler == "Flush":
                self.spotless.Flush(duration)
            elif handler == "just_water":
                self.spotless.just_water(duration)
            elif handler == "just_shampoo":
                self.spotless.just_shampoo(qr_return)
            elif handler == "Empty_tank":
                self.spotless.Empty_tank(duration)
            else:
                self.logger.error(f"Unknown utility handler: {handler}")
                if self.session_logger:
                    self.session_logger.log_error(f"Unknown handler: {handler}")
                    self.session_logger.end_session("error")
                return False
                
            status = "completed"
        except Exception as e:
            self.logger.error(f"Utility session error: {e}")
            if self.session_logger:
                self.session_logger.log_error(str(e))
            status = "error"
            
        # Log session end
        end_time = datetime.now()
        duration_seconds = int((end_time - start_time).total_seconds())
        
        # End session logging
        if self.session_logger:
            self.session_logger.end_session(status)
        
        # Save session log (offline storage)
        self.config_mgr.log_session(
            session_type=session_type,
            qr_code=qr_return,
            start_time=start_time,
            end_time=end_time,
            status=status
        )
        
        # Send email for utility sessions (optional - only for certain types)
        # Uncomment to enable email for utility sessions
        # if self.email_service and session_type in ['quicktest', 'onlydrying']:
        #     self.email_service.send_session_email(
        #         session_type=session_type,
        #         qr_code=qr_return,
        #         machine_id=self._machine_id,
        #         duration_seconds=duration_seconds
        #     )
        
        return status == "completed"
        
    def run_small_bath(self, qr_return: str = "manual"):
        """Run small pet bath session."""
        return self.run_session("small", qr_return)
        
    def run_large_bath(self, qr_return: str = "manual"):
        """Run large pet bath session."""
        return self.run_session("large", qr_return)
        
    def run_diy_bath(self, qr_return: str = "manual"):
        """Run customer DIY bath session."""
        return self.run_session("custdiy", qr_return)
        
    def run_disinfectant(self, qr_return: str = "manual"):
        """Run disinfectant only session."""
        return self.run_session("onlydisinfectant", qr_return)
        
    def run_test(self):
        """Run relay test."""
        return self.run_session("quicktest", "TEST")
        
    # Convenience methods for utility sessions
    def run_dryer(self, qr_return: str = "manual"):
        """Run dryer only session."""
        return self.run_session("onlydrying", qr_return)
        
    def run_water(self):
        """Run water only session."""
        return self.run_session("onlywater")
        
    def run_flush(self):
        """Run flush only session."""
        return self.run_session("onlyflush")
        
    def run_shampoo(self, qr_return: str = "manual"):
        """Run shampoo only session."""
        return self.run_session("onlyshampoo", qr_return)
        
    def run_empty_tank(self):
        """Run empty tank session."""
        return self.run_session("empty001")
        
    def run(self):
        """Main application loop."""
        if not self.start():
            return 1
            
        try:
            # Main loop - will be expanded with QR scanning/UI
            while self.running:
                # Placeholder for main application logic
                time.sleep(1)
                
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
        finally:
            self.stop()
            
        return 0
    
    # =========================================================================
    # Configuration Access
    # =========================================================================
    
    @property
    def machine_id(self) -> str:
        """Get current machine ID."""
        return self._machine_id
    
    def update_session_param(self, session_type: str, **kwargs):
        """Update a session configuration parameter."""
        return self.config_mgr.update_session_config(session_type, **kwargs)
        
    def print_config_status(self):
        """Print current configuration status."""
        self.config_mgr.print_status()
        
    def print_session_config(self, session_type: str):
        """Print configuration for a specific session type."""
        self.config_mgr.print_session_config(session_type)
    
    # =========================================================================
    # Direct GPIO Relay Properties (Raspberry Pi GPIO)
    # =========================================================================
    
    @property
    def dry(self):
        """Access dry relay (GPIO 14) - Direct Raspberry Pi."""
        return self.gpio.dry if self.gpio else None
    
    @property
    def geyser(self):
        """Access geyser relay (GPIO 18) - Direct Raspberry Pi."""
        return self.gpio.geyser if self.gpio else None
    
    # =========================================================================
    # ESP32 Node Device Properties (via MQTT)
    # =========================================================================
    
    # NODE 1 Devices
    @property
    def p1(self): return self.devices.p1 if self.devices else None
    @property
    def p2(self): return self.devices.p2 if self.devices else None
    @property
    def ro1(self): return self.devices.ro1 if self.devices else None
    @property
    def ro2(self): return self.devices.ro2 if self.devices else None
    @property
    def d1(self): return self.devices.d1 if self.devices else None
    @property
    def p3(self): return self.devices.p3 if self.devices else None
    @property
    def pump(self): return self.devices.pump if self.devices else None
    
    # NODE 2 Devices
    @property
    def p4(self): return self.devices.p4 if self.devices else None
    @property
    def p5(self): return self.devices.p5 if self.devices else None
    @property
    def ro3(self): return self.devices.ro3 if self.devices else None
    @property
    def ro4(self): return self.devices.ro4 if self.devices else None
    @property
    def d2(self): return self.devices.d2 if self.devices else None
    @property
    def s7(self): return self.devices.s7 if self.devices else None
    @property
    def s9(self): return self.devices.s9 if self.devices else None
    
    # NODE 3 Devices
    @property
    def s1(self): return self.devices.s1 if self.devices else None
    @property
    def s2(self): return self.devices.s2 if self.devices else None
    @property
    def s3(self): return self.devices.s3 if self.devices else None
    @property
    def s4(self): return self.devices.s4 if self.devices else None
    @property
    def s5(self): return self.devices.s5 if self.devices else None
    @property
    def s6(self): return self.devices.s6 if self.devices else None
    @property
    def s8(self): return self.devices.s8 if self.devices else None


# =============================================================================
# CLI Argument Parser
# =============================================================================
def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Project Spotless - Pet Grooming Automation System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Session Types:
  Bath Sessions:
    small           Small Pet Bath Session
    large           Large Pet Bath Session
    custdiy         Customer DIY Session
    medsmall        Medicated Bath - Small Pet
    medlarge        Medicated Bath - Large Pet
    onlydisinfectant  Disinfectant Only

  Utility Sessions:
    quicktest       Quick Relay Test
    demo            Demo Mode - Sequential Relay Test
    onlydrying      Dryer Only (5 min)
    onlywater       Water Only (90s)
    onlyflush       Flush Only (60s)
    onlyshampoo     Shampoo Only
    empty001        Empty Tank (3 min)

Examples:
    python main.py                     # Start normally
    python main.py --kiosk             # Start with kiosk UI
    python main.py --setup             # Reset machine ID
    python main.py --session small     # Run small bath
    python main.py --session quicktest # Test relays
"""
    )
    
    parser.add_argument(
        '--kiosk', 
        action='store_true',
        help='Start with web-based kiosk UI (http://localhost:5000)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        metavar='PORT',
        help='Port for kiosk web server (default: 5000)'
    )
    
    parser.add_argument(
        '--setup', 
        action='store_true',
        help='Run configuration setup (reset machine ID)'
    )
    
    parser.add_argument(
        '--test', 
        action='store_true',
        help='Run relay test mode (same as --session quicktest)'
    )
    
    parser.add_argument(
        '--config', 
        action='store_true',
        help='Print current configuration and exit'
    )
    
    parser.add_argument(
        '--list', 
        action='store_true',
        help='List all available session types'
    )
    
    parser.add_argument(
        '--session',
        type=str,
        metavar='TYPE',
        help='Run a specific session type (see list below)'
    )
    
    parser.add_argument(
        '--qr',
        type=str,
        default='CLI_TEST',
        metavar='CODE',
        help='QR code / session identifier (default: CLI_TEST)'
    )
    
    return parser.parse_args()


# =============================================================================
# Entry Point
# =============================================================================
def main():
    """Main entry point."""
    # Parse arguments
    args = parse_arguments()
    
    # Get machine ID early for logging (if already configured)
    mgr = get_config_manager()
    machine_id = mgr.get_machine_id(prompt_if_missing=False) or ""
    
    # Setup logging with machine ID
    setup_app_logging(machine_id=machine_id)
    logger = logging.getLogger(__name__)
    
    # Handle --setup flag
    if args.setup:
        logger.info("Running configuration setup...")
        mgr = get_config_manager()
        mgr.clear_machine_id()
        machine_id = mgr.get_machine_id()
        if machine_id:
            config = mgr.load_config()
            mgr.print_status()
            logger.info("Setup complete!")
        return 0
        
    # Handle --list flag
    if args.list:
        mgr = get_config_manager()
        machine_id = mgr.get_machine_id(prompt_if_missing=False)
        if machine_id:
            mgr.load_config()
        
        print("\n" + "=" * 60)
        print("  Available Session Types")
        print("=" * 60)
        print("\n  Bath Sessions (full grooming cycles):")
        print("  " + "-" * 40)
        for session_type in mgr.list_session_types():
            desc = mgr.get_session_description(session_type)
            print(f"    {session_type:20} {desc}")
        print("\n  Utility Sessions (single operations):")
        print("  " + "-" * 40)
        for session_type in mgr.list_utility_types():
            desc = mgr.get_session_description(session_type)
            print(f"    {session_type:20} {desc}")
        print("\n" + "=" * 60 + "\n")
        return 0
        
    # Handle --config flag
    if args.config:
        mgr = get_config_manager()
        machine_id = mgr.get_machine_id(prompt_if_missing=False)
        if machine_id:
            mgr.print_status()
            print("\n--- Bath Session Configurations ---")
            for session_type in mgr.list_session_types():
                mgr.print_session_config(session_type)
            print("\n--- Utility Session Configurations ---")
            for session_type in mgr.list_utility_types():
                mgr.print_session_config(session_type)
        else:
            logger.info("No machine configured. Run with --setup first.")
        return 0
    
    # Create application
    app = SpotlessApplication()
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        app.running = False
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Handle --test flag
    if args.test:
        if app.start():
            logger.info("Running relay test...")
            app.run_test()
            app.stop()
        return 0
        
    # Handle --session flag
    if args.session:
        if app.start():
            logger.info(f"Running {args.session} session with QR: {args.qr}")
            app.run_session(args.session, args.qr)
            app.stop()
        return 0
    
    # Handle --kiosk flag
    if args.kiosk:
        logger.info("Starting kiosk mode...")
        
        if not app.start():
            logger.error("Failed to start application")
            return 1
        
        try:
            # Import and start kiosk server
            from kiosk.web_server import create_app, run_server
            
            # Create Flask app with reference to SpotlessApplication
            flask_app = create_app(app)
            
            logger.info(f"Starting kiosk web server on port {args.port}...")
            logger.info(f"Access kiosk at: http://localhost:{args.port}")
            
            # Run the server (this blocks)
            run_server(host='0.0.0.0', port=args.port, debug=False)
            
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
