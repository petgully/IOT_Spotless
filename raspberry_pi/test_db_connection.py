"""
Database Connection and Session Logging Test Script.

This script tests:
1. Database connectivity
2. Reading session_config table
3. Session logging (if tables exist)
4. Stage logging (if tables exist)
"""
import sys
sys.path.insert(0, '.')
from db_manager import DatabaseManager, DEFAULT_DB_CONFIG
import db_sessions

def test_connection():
    print('=' * 70)
    print('  Database Connection Test - Project Spotless')
    print('=' * 70)
    print(f'Host:     {DEFAULT_DB_CONFIG.host}')
    print(f'Database: {DEFAULT_DB_CONFIG.database}')
    print(f'User:     {DEFAULT_DB_CONFIG.user}')
    print('=' * 70)
    
    db = DatabaseManager(DEFAULT_DB_CONFIG)
    
    print('\n[1] Connecting to database...')
    if not db.connect():
        print('FAILED: Could not connect to database')
        print('\nCheck:')
        print('  1. Aurora endpoint is correct')
        print('  2. Security group allows inbound on port 3306')
        print('  3. Username and password are correct')
        print('  4. Database name is correct')
        return None
        
    print('SUCCESS: Connected!')
    return db

def test_session_configs(db):
    print('\n' + '-' * 70)
    print('  [2] Session Configurations (session_config table)')
    print('-' * 70)
    
    try:
        with db._connection.cursor() as cursor:
            cursor.execute('SELECT id, mobile_number, customer_name, session_type, sval, cval, dval, wval, dryval FROM session_config')
            rows = cursor.fetchall()
            
            for row in rows:
                print(f"  ID: {row['id']:2} | {row['mobile_number']:15} | {row['customer_name']}")
                print(f"       Type: {row['session_type']:10} | sval={row['sval']}, cval={row['cval']}, dval={row['dval']}")
            
            print(f'\n  Total configurations: {len(rows)}')
            return True
    except Exception as e:
        print(f'  Query error: {e}')
        return False

def test_session_logs_table(db):
    print('\n' + '-' * 70)
    print('  [3] Session Logs Table Check')
    print('-' * 70)
    
    try:
        with db._connection.cursor() as cursor:
            # Check if table exists
            cursor.execute("SHOW TABLES LIKE 'session_logs'")
            if not cursor.fetchone():
                print('  WARNING: session_logs table does not exist!')
                print('  Run the CREATE TABLE SQL to create it.')
                return False
            
            # Count records
            cursor.execute('SELECT COUNT(*) as count FROM session_logs')
            count = cursor.fetchone()['count']
            print(f'  Table exists! Records: {count}')
            
            # Show recent sessions if any
            if count > 0:
                cursor.execute('''
                    SELECT id, mobile_number, session_type, status, activated_at 
                    FROM session_logs ORDER BY id DESC LIMIT 5
                ''')
                print('\n  Recent sessions:')
                for row in cursor.fetchall():
                    print(f"    ID: {row['id']} | {row['mobile_number']} | {row['session_type']} | {row['status']}")
            
            return True
    except Exception as e:
        print(f'  Error: {e}')
        return False

def test_session_stages_table(db):
    print('\n' + '-' * 70)
    print('  [4] Session Stages Table Check')
    print('-' * 70)
    
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'session_stages'")
            if not cursor.fetchone():
                print('  WARNING: session_stages table does not exist!')
                print('  Run the CREATE TABLE SQL to create it.')
                return False
            
            cursor.execute('SELECT COUNT(*) as count FROM session_stages')
            count = cursor.fetchone()['count']
            print(f'  Table exists! Records: {count}')
            return True
    except Exception as e:
        print(f'  Error: {e}')
        return False

def test_session_events_table(db):
    print('\n' + '-' * 70)
    print('  [5] Session Events Table Check')
    print('-' * 70)
    
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'session_events'")
            if not cursor.fetchone():
                print('  WARNING: session_events table does not exist!')
                print('  Run the CREATE TABLE SQL to create it.')
                return False
            
            cursor.execute('SELECT COUNT(*) as count FROM session_events')
            count = cursor.fetchone()['count']
            print(f'  Table exists! Records: {count}')
            return True
    except Exception as e:
        print(f'  Error: {e}')
        return False

def test_logging_flow(db):
    print('\n' + '-' * 70)
    print('  [6] Test Logging Flow (Simulation)')
    print('-' * 70)
    
    try:
        # Test session activation
        print('  Simulating session activation...')
        session_id = db_sessions.log_session_activated(
            db,
            mobile_number='TEST_USER',
            machine_id='TEST_MACHINE',
            session_type='test',
            qr_code='TEST_QR_001',
            params={
                'sval': 60, 'cval': 60, 'dval': 30, 'wval': 30,
                'dryval': 120, 'fval': 30, 'wt': 10, 'stval': 5,
                'msgval': 5, 'tdry': 10, 'pr': 20, 'ctype': 100
            }
        )
        
        if session_id:
            print(f'  Session activated! ID: {session_id}')
            
            # Start session
            db_sessions.log_session_start(db, session_id)
            print(f'  Session started!')
            
            # Log a stage
            stage_id = db_sessions.log_stage_start(db, session_id, 'test_stage', 1, 60)
            if stage_id:
                print(f'  Stage started! ID: {stage_id}')
                db_sessions.log_stage_complete(db, stage_id, 58)
                print(f'  Stage completed!')
            
            # Log an event
            db_sessions.log_event(db, session_id, 'test_event', {'test': 'data'})
            print(f'  Event logged!')
            
            # Complete session
            db_sessions.log_session_complete(db, session_id, 120)
            print(f'  Session completed!')
            
            print('\n  SUCCESS: Logging flow works correctly!')
            return True
        else:
            print('  FAILED: Could not create session')
            return False
            
    except Exception as e:
        print(f'  Error: {e}')
        return False

def main():
    db = test_connection()
    if not db:
        return
    
    test_session_configs(db)
    
    logs_exist = test_session_logs_table(db)
    stages_exist = test_session_stages_table(db)
    events_exist = test_session_events_table(db)
    
    if logs_exist and stages_exist and events_exist:
        test_logging_flow(db)
    else:
        print('\n' + '=' * 70)
        print('  MISSING TABLES - Run the following SQL in MySQL Workbench:')
        print('=' * 70)
        print('''
CREATE TABLE IF NOT EXISTS session_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    mobile_number VARCHAR(15) NOT NULL,
    machine_id VARCHAR(20) NOT NULL,
    qr_code VARCHAR(100),
    session_type VARCHAR(50) NOT NULL,
    sval INT, cval INT, dval INT, wval INT, dryval INT, fval INT,
    wt INT, stval INT, msgval INT, tdry INT, pr INT, ctype INT,
    activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_start TIMESTAMP NULL,
    session_end TIMESTAMP NULL,
    total_duration_seconds INT,
    status ENUM('activated','started','in_progress','completed','error','stopped','cancelled') DEFAULT 'activated',
    error_message TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_mobile (mobile_number),
    INDEX idx_machine (machine_id)
);

CREATE TABLE IF NOT EXISTS session_stages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    stage_name VARCHAR(50) NOT NULL,
    stage_order INT NOT NULL,
    planned_duration_seconds INT,
    actual_duration_seconds INT,
    start_time TIMESTAMP NULL,
    end_time TIMESTAMP NULL,
    status ENUM('pending','started','completed','skipped','error') DEFAULT 'pending',
    notes TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (session_id),
    FOREIGN KEY (session_id) REFERENCES session_logs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_data JSON,
    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (session_id),
    FOREIGN KEY (session_id) REFERENCES session_logs(id) ON DELETE CASCADE
);
        ''')
    
    db.disconnect()
    print('\n' + '=' * 70)
    print('  Test Complete!')
    print('=' * 70)

if __name__ == '__main__':
    main()
