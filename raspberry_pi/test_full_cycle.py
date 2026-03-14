#!/usr/bin/env python3
"""
=============================================================================
Full Integration Test - Project Spotless
=============================================================================
Tests the complete session cycle:
1. Database connectivity
2. QR code validation
3. Pull session config from DB
4. Session logging
5. Stage tracking
6. ESP32 node status (simulated)
7. Session completion
8. Database update
9. Email notification (optional)

Run: python test_full_cycle.py
=============================================================================
"""

import sys
import os
import time
import logging
from datetime import datetime

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title):
    print("\n" + "-" * 70)
    print(f"  {title}")
    print("-" * 70)


def print_result(test_name, success, message=""):
    status = "[PASS]" if success else "[FAIL]"
    print(f"  {status} | {test_name}")
    if message:
        print(f"         -> {message}")


def test_database_connection():
    """Test database connectivity."""
    print_section("1. Database Connection")
    
    try:
        from db_manager import DatabaseManager, DEFAULT_DB_CONFIG
        
        db = DatabaseManager(DEFAULT_DB_CONFIG)
        print(f"  Host: {DEFAULT_DB_CONFIG.host}")
        print(f"  Database: {DEFAULT_DB_CONFIG.database}")
        
        if db.connect():
            print_result("Database connection", True, "Connected successfully")
            return db
        else:
            print_result("Database connection", False, "Connection failed")
            return None
    except Exception as e:
        print_result("Database connection", False, str(e))
        return None


def test_session_config_fetch(db, mobile_number="DEFAULT_SMALL"):
    """Test fetching session config from database."""
    print_section("2. Fetch Session Config from DB")
    
    try:
        config = db.get_session_config(mobile_number)
        
        if config:
            print(f"  Mobile: {config.get('mobile_number')}")
            print(f"  Name: {config.get('customer_name')}")
            print(f"  Type: {config.get('session_type')}")
            print(f"  Params: sval={config.get('sval')}, cval={config.get('cval')}, dryval={config.get('dryval')}")
            print_result("Fetch session config", True, f"Found config for {mobile_number}")
            return config
        else:
            print_result("Fetch session config", False, f"No config found for {mobile_number}")
            return None
    except Exception as e:
        print_result("Fetch session config", False, str(e))
        return None


def test_qr_validation():
    """Test QR code validation logic."""
    print_section("3. QR Code Validation")
    
    try:
        # Import the web server's validate function
        from kiosk.web_server import validate_qr_code, get_database
        
        # Ensure database is connected
        get_database()
        
        test_cases = [
            ("DEFAULT_SMALL", "small", True),
            ("SM12345", "small", False),
            ("LG67890", "large", False),
            ("TEST001", "quicktest", False),
            ("DRY001", "onlydrying", False),
        ]
        
        all_passed = True
        for qr_code, expected_type, expect_db in test_cases:
            result = validate_qr_code(qr_code)
            if result and result.get('session_type') == expected_type:
                print_result(f"QR: {qr_code}", True, 
                           f"Type: {result['session_type']}, From DB: {result.get('from_database', False)}")
            else:
                print_result(f"QR: {qr_code}", False, 
                           f"Expected {expected_type}, got {result}")
                all_passed = False
        
        return all_passed
    except Exception as e:
        print_result("QR validation", False, str(e))
        return False


def test_session_logging(db):
    """Test session logging to database."""
    print_section("4. Session Logging (Full Cycle)")
    
    # First check if tables exist
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM session_logs LIKE 'activated_at'")
            has_activated_at = cursor.fetchone() is not None
            
            cursor.execute("SHOW TABLES LIKE 'session_stages'")
            has_stages_table = cursor.fetchone() is not None
            
            cursor.execute("SHOW TABLES LIKE 'session_events'")
            has_events_table = cursor.fetchone() is not None
            
            if not has_activated_at or not has_stages_table or not has_events_table:
                print("  [WARNING] Database tables need to be updated!")
                print("  Missing columns/tables:")
                if not has_activated_at:
                    print("    - session_logs.activated_at column")
                if not has_stages_table:
                    print("    - session_stages table")
                if not has_events_table:
                    print("    - session_events table")
                print("\n  Please run the CREATE TABLE SQL statements provided earlier.")
                print_result("Session logging", False, "Tables need update")
                return False
    except Exception as e:
        print(f"  Error checking tables: {e}")
        print_result("Session logging", False, "Could not check table structure")
        return False
    
    try:
        machine_id = "TEST_MACHINE"
        qr_code = "DEFAULT_SMALL"
        session_type = "small"
        
        # Step 1: Log session activation
        print("  Step 1: Activating session...")
        session_id = db.log_session_activated(
            mobile_number="TEST_USER_001",
            machine_id=machine_id,
            session_type=session_type,
            qr_code=qr_code,
            params={
                'sval': 120, 'cval': 120, 'dval': 60, 'wval': 60,
                'dryval': 480, 'fval': 60, 'wt': 30, 'stval': 10,
                'msgval': 10, 'tdry': 30, 'pr': 20, 'ctype': 100
            }
        )
        
        if not session_id:
            print_result("Session activation", False, "Failed to create session")
            return False
        print_result("Session activation", True, f"Session ID: {session_id}")
        
        # Step 2: Start session
        print("  Step 2: Starting session...")
        db.log_session_start(session_id)
        db.log_session_in_progress(session_id)
        print_result("Session start", True)
        
        # Step 3: Log stages
        print("  Step 3: Logging stages...")
        stages = [
            ("shampoo", 5),
            ("rinse", 3),
            ("conditioner", 5),
            ("drying", 5),
        ]
        
        stage_order = 0
        for stage_name, duration in stages:
            stage_order += 1
            stage_id = db.log_stage_start(session_id, stage_name, stage_order, duration)
            
            if stage_id:
                # Simulate stage running
                time.sleep(0.5)
                db.log_stage_complete(stage_id, duration)
                print_result(f"Stage: {stage_name}", True, f"Duration: {duration}s")
            else:
                print_result(f"Stage: {stage_name}", False)
        
        # Step 4: Log events
        print("  Step 4: Logging events...")
        db.log_event(session_id, "relay_on", {"relay": "shampoo_pump", "node": 1})
        db.log_event(session_id, "relay_off", {"relay": "shampoo_pump", "node": 1})
        print_result("Event logging", True)
        
        # Step 5: Complete session
        print("  Step 5: Completing session...")
        total_duration = sum(d for _, d in stages)
        db.log_session_complete(session_id, total_duration)
        print_result("Session complete", True, f"Total duration: {total_duration}s")
        
        # Step 6: Verify in database
        print("  Step 6: Verifying in database...")
        details = db.get_session_details(session_id)
        if details and details.get('session'):
            session = details['session']
            stages_count = len(details.get('stages', []))
            events_count = len(details.get('events', []))
            print_result("Database verification", True, 
                        f"Status: {session['status']}, Stages: {stages_count}, Events: {events_count}")
            return True
        else:
            print_result("Database verification", False, "Could not retrieve session details")
            return False
            
    except Exception as e:
        print_result("Session logging", False, str(e))
        import traceback
        traceback.print_exc()
        return False


def test_esp32_nodes():
    """Test ESP32 node configuration (simulated)."""
    print_section("5. ESP32 Node Configuration (Simulated)")
    
    try:
        from config import NODES
        from device_map import devices  # Global DeviceMap instance
        
        # Check node configuration
        print(f"  Configured Nodes: {len(NODES)}")
        for node_id, node_config in NODES.items():
            print(f"    - {node_id}: {node_config.get('relay_count', 0)} relays")
        
        print_result("Node configuration", True, f"{len(NODES)} nodes configured")
        
        # Check device mapping from DeviceMap class
        device_mapping = devices.all_devices()  # Use the method to get devices
        print(f"\n  Device Mappings: {len(device_mapping)}")
        
        node1_devices = [k for k, v in device_mapping.items() if v.node_id == 'spotless_node1']
        node2_devices = [k for k, v in device_mapping.items() if v.node_id == 'spotless_node2']
        node3_devices = [k for k, v in device_mapping.items() if v.node_id == 'spotless_node3']
        
        print(f"    Node 1: {len(node1_devices)} devices -> {', '.join(node1_devices)}")
        print(f"    Node 2: {len(node2_devices)} devices -> {', '.join(node2_devices)}")
        print(f"    Node 3: {len(node3_devices)} devices -> {', '.join(node3_devices)}")
        
        print_result("Device mapping", True, f"{len(device_mapping)} devices mapped")
        return True
        
    except Exception as e:
        print_result("ESP32 nodes", False, str(e))
        return False


def test_gpio_controller():
    """Test GPIO controller (simulated mode)."""
    print_section("6. GPIO Controller (Raspberry Pi)")
    
    try:
        from gpio_controller import GPIOController, GPIO_AVAILABLE
        
        # Initialize (will auto-simulate on Windows)
        gpio = GPIOController()
        gpio.initialize()
        
        mode = "Hardware" if GPIO_AVAILABLE else "Simulated"
        print(f"  Mode: {mode}")
        print(f"  Configured relays: {list(gpio._relays.keys())}")
        
        # Test relay operations
        gpio.dry.on()
        print_result("Dry relay ON", True)
        
        gpio.geyser.on()
        print_result("Geyser relay ON", True)
        
        gpio.all_off()
        print_result("All relays OFF", True)
        
        return True
        
    except Exception as e:
        print_result("GPIO controller", False, str(e))
        return False


def test_email_service():
    """Test email service (connection check only)."""
    print_section("7. Email Service")
    
    try:
        from email_service import check_internet, EmailConfig
        
        print("  Checking internet connectivity...")
        has_internet = check_internet()
        
        # Create config instance to get default values
        config = EmailConfig()
        
        if has_internet:
            print_result("Internet connectivity", True)
            print(f"  Email sender: {config.sender}")
            print(f"  Email receiver: {config.receiver}")
            print_result("Email configuration", True, "Ready to send notifications")
        else:
            print_result("Internet connectivity", False, "No internet - emails will be skipped")
        
        return has_internet
        
    except Exception as e:
        print_result("Email service", False, str(e))
        return False


def test_kiosk_webserver():
    """Test kiosk web server components."""
    print_section("8. Kiosk Web Server")
    
    try:
        from kiosk.web_server import app, SESSION_STAGES
        
        print(f"  Flask app: {app.name}")
        print(f"  Session types: {len(SESSION_STAGES)}")
        
        for session_type, stages in SESSION_STAGES.items():
            total_duration = sum(s['duration'] for s in stages)
            print(f"    - {session_type}: {len(stages)} stages, {total_duration}s total")
        
        print_result("Web server", True, "Flask app configured")
        return True
        
    except Exception as e:
        print_result("Web server", False, str(e))
        return False


def run_simulated_session(db, duration_per_stage=2):
    """Run a simulated session with real-time logging."""
    print_section("9. Simulated Full Session (Accelerated)")
    
    # Check if tables are ready
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM session_logs LIKE 'activated_at'")
            if not cursor.fetchone():
                print("  [SKIP] Tables not ready - run CREATE TABLE SQL first")
                print_result("Simulated session", False, "Tables need update")
                return False
    except:
        pass
    
    try:
        machine_id = "SIM_MACHINE"
        qr_code = "SIM_TEST_001"
        session_type = "small"
        
        print(f"  Session Type: {session_type}")
        print(f"  QR Code: {qr_code}")
        print(f"  Stage Duration: {duration_per_stage}s each (accelerated)\n")
        
        # Stages to simulate
        stages = [
            ("welcome", "Welcome"),
            ("shampoo", "Shampoo"),
            ("rinse1", "First Rinse"),
            ("conditioner", "Conditioner"),
            ("rinse2", "Final Rinse"),
            ("drying", "Drying"),
            ("complete", "Complete"),
        ]
        
        # Start session
        session_id = db.log_session_activated(
            mobile_number="SIM_USER",
            machine_id=machine_id,
            session_type=session_type,
            qr_code=qr_code,
            params={'sval': 120, 'cval': 120, 'dryval': 480}
        )
        
        if not session_id:
            print_result("Session start", False, "Could not create session - check DB tables")
            return False
        
        db.log_session_start(session_id)
        db.log_session_in_progress(session_id)
        print(f"  Session ID: {session_id}")
        print()
        
        start_time = time.time()
        
        for i, (stage_name, stage_label) in enumerate(stages):
            stage_id = db.log_stage_start(session_id, stage_name, i+1, duration_per_stage)
            
            # Progress bar simulation
            print(f"  [{i+1}/{len(stages)}] {stage_label}...", end=" ", flush=True)
            
            for j in range(duration_per_stage):
                progress = int((j+1) / duration_per_stage * 20)
                bar = "#" * progress + "-" * (20 - progress)
                print(f"\r  [{i+1}/{len(stages)}] {stage_label}: [{bar}] {j+1}s/{duration_per_stage}s", 
                      end="", flush=True)
                time.sleep(1)
            
            if stage_id:
                db.log_stage_complete(stage_id, duration_per_stage)
            
            print(f"\r  [{i+1}/{len(stages)}] {stage_label}: [####################] Complete!")
        
        total_duration = int(time.time() - start_time)
        db.log_session_complete(session_id, total_duration)
        
        print()
        print_result("Simulated session", True, f"Completed in {total_duration}s")
        
        # Verify final state
        details = db.get_session_details(session_id)
        if details:
            print(f"\n  Final Status: {details['session']['status']}")
            print(f"  Stages Logged: {len(details['stages'])}")
        
        return True
        
    except Exception as e:
        print_result("Simulated session", False, str(e))
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all integration tests."""
    print_header("Project Spotless - Full Integration Test")
    print(f"  Started: {datetime.now()}")
    print("  This test simulates a complete session cycle")
    
    results = {}
    
    # Test 1: Database connection
    db = test_database_connection()
    results['database'] = db is not None
    
    if not db:
        print("\n\n  [WARNING] Cannot continue without database connection!")
        print("  Please ensure the database tables are created and try again.\n")
        return
    
    # Test 2: Fetch session config
    config = test_session_config_fetch(db)
    results['fetch_config'] = config is not None
    
    # Test 3: QR validation
    results['qr_validation'] = test_qr_validation()
    
    # Test 4: Session logging
    results['session_logging'] = test_session_logging(db)
    
    # Test 5: ESP32 nodes
    results['esp32_nodes'] = test_esp32_nodes()
    
    # Test 6: GPIO controller
    results['gpio_controller'] = test_gpio_controller()
    
    # Test 7: Email service
    results['email_service'] = test_email_service()
    
    # Test 8: Kiosk web server
    results['kiosk_webserver'] = test_kiosk_webserver()
    
    # Test 9: Simulated full session
    results['simulated_session'] = run_simulated_session(db, duration_per_stage=2)
    
    # Summary
    print_header("Test Summary")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, success in results.items():
        print_result(test_name.replace('_', ' ').title(), success)
    
    print()
    print(f"  Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n  [OK] All tests passed! System is ready for hardware integration.\n")
    else:
        print(f"\n  [WARNING] {total - passed} test(s) failed. Please review and fix before deployment.\n")
    
    # Cleanup
    if db:
        db.disconnect()


if __name__ == "__main__":
    main()
