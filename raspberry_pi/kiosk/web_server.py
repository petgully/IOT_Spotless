"""
=============================================================================
Kiosk Web Server - Project Spotless
=============================================================================
Flask + Flask-SocketIO server for the kiosk UI.

Features:
- REST API for session control
- WebSocket for real-time progress updates
- Barcode scanner input handling
- Session status broadcasting

Run:
    python -m kiosk.web_server
    
Or integrated with main.py
=============================================================================
"""

import os
import sys
import logging
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Flask app and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'spotless-kiosk-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global reference to SpotlessApplication (set by main.py)
_spotless_app = None
_session_thread = None
_current_session = None


def create_app(spotless_app=None):
    """Create and configure the Flask app."""
    global _spotless_app
    _spotless_app = spotless_app
    return app


# =============================================================================
# Session Stage Definitions
# =============================================================================
SESSION_STAGES = {
    "small": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 20, "image": "preparing.png"},
        {"name": "shampoo", "label": "Shampoo Stage", "duration": 120, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 60, "image": "water.png"},
        {"name": "conditioner", "label": "Conditioner Stage", "duration": 120, "image": "conditioner.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 60, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 480, "image": "drying.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "large": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 20, "image": "preparing.png"},
        {"name": "shampoo", "label": "Shampoo Stage", "duration": 150, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 80, "image": "water.png"},
        {"name": "conditioner", "label": "Conditioner Stage", "duration": 150, "image": "conditioner.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 80, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 600, "image": "drying.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "custdiy": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 15, "image": "preparing.png"},
        {"name": "shampoo", "label": "Shampoo Stage", "duration": 100, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 60, "image": "water.png"},
        {"name": "conditioner", "label": "Conditioner Stage", "duration": 100, "image": "conditioner.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 60, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 600, "image": "drying.png"},
        {"name": "disinfectant", "label": "Disinfectant", "duration": 60, "image": "disinfect.png"},
        {"name": "autoflush", "label": "Auto Flush", "duration": 120, "image": "flush.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "medsmall": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 20, "image": "preparing.png"},
        {"name": "shampoo", "label": "Medicated Shampoo", "duration": 80, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 60, "image": "water.png"},
        {"name": "medbath", "label": "Medicated Bath", "duration": 80, "image": "medbath.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 60, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 480, "image": "drying.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "medlarge": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "preparing", "label": "Getting Ready", "duration": 20, "image": "preparing.png"},
        {"name": "shampoo", "label": "Medicated Shampoo", "duration": 100, "image": "shampoo.png"},
        {"name": "massage1", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse1", "label": "Water Rinse", "duration": 60, "image": "water.png"},
        {"name": "medbath", "label": "Medicated Bath", "duration": 100, "image": "medbath.png"},
        {"name": "massage2", "label": "Massage Time", "duration": 10, "image": "massage.png"},
        {"name": "rinse2", "label": "Final Rinse", "duration": 60, "image": "water.png"},
        {"name": "toweldry", "label": "Towel Dry", "duration": 30, "image": "toweldry.png"},
        {"name": "drying", "label": "Drying Time", "duration": 600, "image": "drying.png"},
        {"name": "complete", "label": "Session Complete", "duration": 10, "image": "complete.png"},
    ],
    "onlydisinfectant": [
        {"name": "welcome", "label": "Welcome to Spotless", "duration": 10, "image": "welcome.png"},
        {"name": "disinfectant", "label": "Disinfecting Tub", "duration": 60, "image": "disinfect.png"},
        {"name": "autoflush", "label": "Auto Flush", "duration": 120, "image": "flush.png"},
        {"name": "complete", "label": "Cleanup Complete", "duration": 10, "image": "complete.png"},
    ],
    "quicktest": [
        {"name": "testing", "label": "Testing All Relays", "duration": 90, "image": "testing.png"},
        {"name": "complete", "label": "Test Complete", "duration": 5, "image": "complete.png"},
    ],
    "onlydrying": [
        {"name": "drying", "label": "Drying Only", "duration": 300, "image": "drying.png"},
        {"name": "complete", "label": "Drying Complete", "duration": 5, "image": "complete.png"},
    ],
    "onlywater": [
        {"name": "water", "label": "Water Rinse", "duration": 90, "image": "water.png"},
        {"name": "complete", "label": "Rinse Complete", "duration": 5, "image": "complete.png"},
    ],
    "onlyflush": [
        {"name": "flush", "label": "Flushing System", "duration": 60, "image": "flush.png"},
        {"name": "complete", "label": "Flush Complete", "duration": 5, "image": "complete.png"},
    ],
    "onlyshampoo": [
        {"name": "shampoo", "label": "Shampoo Only", "duration": 60, "image": "shampoo.png"},
        {"name": "complete", "label": "Shampoo Complete", "duration": 5, "image": "complete.png"},
    ],
    "empty001": [
        {"name": "emptying", "label": "Emptying Tank", "duration": 180, "image": "empty.png"},
        {"name": "complete", "label": "Tank Empty", "duration": 5, "image": "complete.png"},
    ],
    "demo": [
        {"name": "demo", "label": "Demo Mode - Testing Relays", "duration": 200, "image": "testing.png"},
        {"name": "complete", "label": "Demo Complete", "duration": 5, "image": "complete.png"},
    ],
}


# =============================================================================
# Routes
# =============================================================================
@app.route('/')
def index():
    """Main kiosk page."""
    machine_id = ""
    if _spotless_app:
        machine_id = _spotless_app.machine_id or ""
    return render_template('index.html', machine_id=machine_id)


@app.route('/session')
def session_page():
    """Session progress page."""
    return render_template('session.html')


@app.route('/api/status')
def get_status():
    """Get current system status."""
    status = {
        'ready': _spotless_app is not None,
        'machine_id': _spotless_app.machine_id if _spotless_app else None,
        'session_active': _current_session is not None,
        'current_session': _current_session,
    }
    return jsonify(status)


@app.route('/api/session/start', methods=['POST'])
def start_session():
    """Start a bath session."""
    global _session_thread, _current_session
    
    data = request.json
    qr_code = data.get('qr_code', '').strip()
    
    if not qr_code:
        return jsonify({'success': False, 'error': 'QR code is required'}), 400
    
    if _current_session:
        return jsonify({'success': False, 'error': 'A session is already in progress'}), 400
    
    # Validate QR code and get session info (type + params from DB)
    session_info = validate_qr_code(qr_code)
    
    if not session_info or not session_info.get('session_type'):
        socketio.emit('scan_failed', {
            'message': 'Sorry, QR code validation failed. Please contact management.'
        })
        return jsonify({
            'success': False, 
            'error': 'Invalid QR code. Please contact management.'
        }), 400
    
    session_type = session_info['session_type']
    customer_name = session_info.get('customer_name')
    from_db = session_info.get('from_database', False)
    
    # Get stages for this session type
    stages = SESSION_STAGES.get(session_type, SESSION_STAGES['small'])
    
    # Set current session
    _current_session = {
        'qr_code': qr_code,
        'session_type': session_type,
        'customer_name': customer_name,
        'from_database': from_db,
        'params': session_info.get('params'),
        'stages': stages,
        'current_stage': 0,
        'stage_progress': 0,
        'started_at': datetime.now().isoformat(),
    }
    
    # Emit scan success with customer info
    socketio.emit('scan_success', {
        'qr_code': qr_code,
        'session_type': session_type,
        'customer_name': customer_name,
        'from_database': from_db,
        'stages': stages,
    })
    
    logger.info(f"Starting session: type={session_type}, qr={qr_code}, customer={customer_name}, from_db={from_db}")
    
    # Start session in background thread
    _session_thread = threading.Thread(
        target=run_session_with_progress,
        args=(session_type, qr_code, stages, session_info),
        daemon=True
    )
    _session_thread.start()
    
    return jsonify({
        'success': True,
        'session_type': session_type,
        'customer_name': customer_name,
        'from_database': from_db,
        'qr_code': qr_code,
        'stages': stages,
    })


@app.route('/api/session/stop', methods=['POST'])
def stop_session():
    """Emergency stop the current session."""
    global _current_session
    
    if _spotless_app:
        _spotless_app.all_off()
    
    _current_session = None
    
    socketio.emit('session_stopped', {
        'message': 'Session stopped by user'
    })
    
    return jsonify({'success': True, 'message': 'Session stopped'})


@app.route('/api/session_types')
def get_session_types():
    """Get available session types."""
    return jsonify({
        'bath_sessions': ['small', 'large', 'custdiy', 'medsmall', 'medlarge', 'onlydisinfectant'],
        'utility_sessions': ['quicktest', 'demo', 'onlydrying', 'onlywater', 'onlyflush', 'onlyshampoo', 'empty001'],
    })


# =============================================================================
# WebSocket Events
# =============================================================================
@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    logger.info('Client connected')
    emit('connected', {'status': 'connected'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    logger.info('Client disconnected')


@socketio.on('scan_input')
def handle_scan_input(data):
    """Handle barcode/QR scanner input."""
    qr_code = data.get('qr_code', '').strip()
    logger.info(f"Received scan input: {qr_code}")
    
    # Trigger session start via API
    # This allows the same logic to be used for both WebSocket and REST


# =============================================================================
# Database Integration
# =============================================================================
_db_manager = None

def get_database():
    """Get database manager instance."""
    global _db_manager
    if _db_manager is None:
        try:
            from db_manager import DatabaseManager, DEFAULT_DB_CONFIG
            _db_manager = DatabaseManager(DEFAULT_DB_CONFIG)
            _db_manager.connect()
            logger.info(f"Database connected: {DEFAULT_DB_CONFIG.host}")
        except Exception as e:
            logger.warning(f"Database not available: {e}")
            _db_manager = None
    return _db_manager


# =============================================================================
# Helper Functions
# =============================================================================
def validate_qr_code(qr_code: str) -> dict:
    """
    Validate QR code and return session info including type and params.
    
    Priority:
    1. Booking lookup (PG prefix - from booking app)
    2. Session config lookup (legacy)
    3. Prefix matching for utility sessions
    4. Default session types
    
    Returns:
        dict with 'session_type', 'params', 'customer_name', 'mobile_number', 'booking_code'
        or None if invalid
    """
    qr_upper = qr_code.upper().strip()
    result = {
        'session_type': None,
        'params': None,
        'customer_name': None,
        'pet_name': None,
        'mobile_number': qr_code,
        'booking_code': None,
        'from_database': False,
    }
    
    db = get_database()
    if db and db.is_connected:
        # First, check if it's a booking code (starts with PG)
        if qr_upper.startswith('PG'):
            try:
                with db._connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT b.*, p.name as pet_name, c.name as customer_name
                        FROM bookings b
                        JOIN pets p ON b.pet_id = p.id
                        JOIN customers c ON b.customer_id = c.id
                        WHERE b.booking_code = %s
                    """, (qr_code,))
                    booking = cursor.fetchone()
                    
                    if booking:
                        result['session_type'] = booking.get('session_type', 'small')
                        result['booking_code'] = booking.get('booking_code')
                        result['customer_name'] = booking.get('customer_name')
                        result['pet_name'] = booking.get('pet_name')
                        result['params'] = {
                            'sval': booking.get('sval', 120),
                            'cval': booking.get('cval', 120),
                            'dval': booking.get('dval', 60),
                            'wval': booking.get('wval', 60),
                            'dryval': booking.get('dryval', 480),
                            'fval': booking.get('fval', 60),
                            'wt': booking.get('wt', 30),
                            'stval': 10,
                            'msgval': 10,
                            'tdry': 30,
                            'pr': 20,
                            'ctype': booking.get('ctype', 100),
                        }
                        result['from_database'] = True
                        logger.info(f"Found booking: {qr_code} -> {result['session_type']} for {result['pet_name']}")
                        
                        # Update booking status to confirmed
                        cursor.execute("""
                            UPDATE bookings SET status = 'confirmed' WHERE booking_code = %s
                        """, (qr_code,))
                        
                        return result
            except Exception as e:
                logger.warning(f"Booking lookup failed: {e}")
        
        # Try session_config lookup (legacy/default configs)
        try:
            config = db.get_session_config(qr_code)
            if config:
                result['session_type'] = config.get('session_type', 'small')
                result['params'] = {
                    'sval': config.get('sval', 120),
                    'cval': config.get('cval', 120),
                    'dval': config.get('dval', 60),
                    'wval': config.get('wval', 60),
                    'dryval': config.get('dryval', 480),
                    'fval': config.get('fval', 60),
                    'wt': config.get('wt', 30),
                    'stval': config.get('stval', 10),
                    'msgval': config.get('msgval', 10),
                    'tdry': config.get('tdry', 30),
                    'pr': config.get('pr', 20),
                    'ctype': config.get('ctype', 100),
                }
                result['customer_name'] = config.get('customer_name')
                result['from_database'] = True
                logger.info(f"Found session config: {qr_code} -> {result['session_type']}")
                return result
        except Exception as e:
            logger.warning(f"Session config lookup failed: {e}")
    
    # Mapping prefixes to session types (for utility/test sessions)
    prefix_map = {
        'SM': 'small',
        'LG': 'large',
        'DIY': 'custdiy',
        'MDS': 'medsmall',
        'MDL': 'medlarge',
        'DIS': 'onlydisinfectant',
        'TEST': 'quicktest',
        'DEMO': 'demo',
        'DRY': 'onlydrying',
        'WATER': 'onlywater',
        'FLUSH': 'onlyflush',
        'SHAMP': 'onlyshampoo',
        'EMPTY': 'empty001',
        'SMALL': 'small',
        'LARGE': 'large',
        'DEFAULT_SMALL': 'small',
        'DEFAULT_LARGE': 'large',
        'DEFAULT_DIY': 'custdiy',
    }
    
    for prefix, session_type in prefix_map.items():
        if qr_upper.startswith(prefix):
            result['session_type'] = session_type
            # Get default params from DB or use local defaults
            if db and db.is_connected:
                try:
                    default_config = db.get_session_by_type(session_type)
                    if default_config:
                        result['params'] = {k: v for k, v in default_config.items() 
                                          if k in ['sval', 'cval', 'dval', 'wval', 'dryval', 
                                                  'fval', 'wt', 'stval', 'msgval', 'tdry', 'pr', 'ctype']}
                except:
                    pass
            return result
    
    # If no prefix match, check if it's a known session type directly (case-insensitive)
    qr_lower = qr_code.lower().strip()
    if qr_lower in SESSION_STAGES:
        result['session_type'] = qr_lower
        return result
    
    # If we get here, the QR code is invalid
    # Do NOT default to 'small' - return None to indicate invalid code
    logger.warning(f"Invalid QR code: {qr_code} - not found in database, prefixes, or valid session types")
    return None


def run_session_with_progress(session_type: str, qr_code: str, stages: list, 
                               session_info: dict = None):
    """
    Run the actual bath session and emit progress updates.
    Includes database logging for analytics.
    """
    global _current_session
    
    db = get_database()
    db_session_id = None
    machine_id = _spotless_app.machine_id if _spotless_app else 'UNKNOWN'
    params = session_info.get('params') if session_info else None
    mobile_number = session_info.get('mobile_number', qr_code) if session_info else qr_code
    start_time = datetime.now()
    
    try:
        # Check if SpotlessApplication is initialized
        if not _spotless_app:
            logger.error("SpotlessApplication not initialized! Cannot run session.")
            socketio.emit('session_error', {
                'message': 'System not initialized. Please restart the application.'
            })
            return
        
        # Log session activation to database
        if db and db.is_connected:
            db_session_id = db.log_session_activated(
                mobile_number=mobile_number,
                machine_id=machine_id,
                session_type=session_type,
                qr_code=qr_code,
                params=params
            )
            if db_session_id:
                db.log_session_start(db_session_id)
                db.log_session_in_progress(db_session_id)
                logger.info(f"DB Session logged - ID: {db_session_id}")
        
        # Start the actual session execution in a separate thread
        # This will run the hardware commands (relays, etc.)
        def run_session_with_error_handling():
            try:
                logger.info(f"🚀 Starting hardware session: {session_type} for {qr_code}")
                result = _spotless_app.run_session(session_type, qr_code)
                logger.info(f"✅ Hardware session completed: {session_type}, result={result}")
            except Exception as e:
                logger.error(f"❌ Hardware session FAILED: {session_type} - Error: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
        
        session_thread = threading.Thread(
            target=run_session_with_error_handling,
            daemon=True
        )
        session_thread.start()
        logger.info(f"Started actual session execution thread: {session_type} for {qr_code}")
        
        total_stages = len(stages)
        stage_order = 0
        
        for i, stage in enumerate(stages):
            if _current_session is None:
                # Session was stopped
                if db and db_session_id:
                    duration = int((datetime.now() - start_time).total_seconds())
                    db.log_session_stopped(db_session_id, duration)
                return
            
            stage_name = stage['name']
            stage_label = stage['label']
            stage_duration = stage['duration']
            stage_image = stage['image']
            stage_order += 1
            
            # Update current session
            _current_session['current_stage'] = i
            _current_session['stage_progress'] = 0
            
            # Log stage start to database
            db_stage_id = None
            if db and db_session_id:
                db_stage_id = db.log_stage_start(
                    db_session_id, stage_name, stage_order, stage_duration
                )
            
            stage_start_time = datetime.now()
            
            # Emit stage start
            socketio.emit('stage_start', {
                'stage_index': i,
                'stage_name': stage_name,
                'stage_label': stage_label,
                'stage_duration': stage_duration,
                'stage_image': stage_image,
                'total_stages': total_stages,
            })
            
            # Run actual stage (or simulate for testing)
            import time
            for second in range(stage_duration):
                if _current_session is None:
                    # Session stopped mid-stage
                    if db and db_stage_id:
                        actual_duration = int((datetime.now() - stage_start_time).total_seconds())
                        db.log_stage_error(db_stage_id, "Session stopped by user")
                    return
                
                progress = int((second + 1) / stage_duration * 100)
                remaining = stage_duration - second - 1
                
                _current_session['stage_progress'] = progress
                
                # Emit progress update every second
                socketio.emit('stage_progress', {
                    'stage_index': i,
                    'stage_name': stage_name,
                    'progress': progress,
                    'elapsed': second + 1,
                    'remaining': remaining,
                    'total_duration': stage_duration,
                })
                
                time.sleep(1)
            
            # Log stage complete
            if db and db_stage_id:
                actual_duration = int((datetime.now() - stage_start_time).total_seconds())
                db.log_stage_complete(db_stage_id, actual_duration)
            
            # Emit stage complete
            socketio.emit('stage_complete', {
                'stage_index': i,
                'stage_name': stage_name,
            })
        
        # Calculate total duration
        total_duration = int((datetime.now() - start_time).total_seconds())
        
        # Log session complete to database
        if db and db_session_id:
            db.log_session_complete(db_session_id, total_duration)
            logger.info(f"Session completed - ID: {db_session_id}, Duration: {total_duration}s")
        
        # Update booking status if this was a booking
        booking_code = session_info.get('booking_code') if session_info else None
        if db and booking_code:
            try:
                with db._connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE bookings SET status = 'completed' WHERE booking_code = %s
                    """, (booking_code,))
                    logger.info(f"Booking {booking_code} marked as completed")
            except Exception as e:
                logger.warning(f"Failed to update booking status: {e}")
        
        # Session complete
        socketio.emit('session_complete', {
            'qr_code': qr_code,
            'session_type': session_type,
            'duration': total_duration,
            'message': 'Thank you for using Petgully Spotless!',
        })
        
        # Send email notification (if app is connected)
        if _spotless_app and hasattr(_spotless_app, 'email_service'):
            try:
                _spotless_app.email_service.send_session_email(
                    session_type=session_type,
                    machine_id=machine_id,
                    qr_code=qr_code,
                    duration=total_duration
                )
            except Exception as e:
                logger.warning(f"Email notification failed: {e}")
        
    except Exception as e:
        logger.error(f"Session error: {e}")
        
        # Log error to database
        if db and db_session_id:
            db.log_session_error(db_session_id, str(e))
        
        socketio.emit('session_error', {
            'error': str(e),
            'message': 'An error occurred. Please contact management.'
        })
    finally:
        _current_session = None


def emit_stage_update(stage_name: str, label: str, progress: int, remaining: int):
    """Emit a stage update to all connected clients."""
    socketio.emit('stage_update', {
        'stage_name': stage_name,
        'label': label,
        'progress': progress,
        'remaining_seconds': remaining,
    })


# =============================================================================
# Run Server
# =============================================================================
def run_server(host='0.0.0.0', port=5000, debug=False):
    """Run the Flask-SocketIO server."""
    logger.info(f"Starting kiosk server on {host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run_server(debug=True)
