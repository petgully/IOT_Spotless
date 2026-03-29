"""
=============================================================================
Kiosk Web Server - Project Spotless
=============================================================================
Flask + Flask-SocketIO server for the kiosk UI.

This module is thin — it only handles HTTP routes and WebSocket events.
Business logic lives in:
    qr_validator.py   - QR code validation
    session_runner.py  - Background session execution
    session_stages.py  - Stage definitions
    db_manager.py      - Database connection
=============================================================================
"""

import os
import sys
import logging
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_stages import get_stages, get_known_session_types
from qr_validator import validate_qr_code
from session_runner import SessionRunner

logger = logging.getLogger(__name__)

# Flask app and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'spotless-kiosk-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Injected at startup by main.py via create_app()
_spotless_app = None
_session_runner: SessionRunner = None
_db = None


def create_app(spotless_app=None):
    """Create and configure the Flask app."""
    global _spotless_app, _session_runner, _db
    _spotless_app = spotless_app
    _db = _get_database()
    _session_runner = SessionRunner(
        spotless_app=spotless_app,
        db=_db,
        emit=lambda event, data: socketio.emit(event, data),
    )
    return app


# =============================================================================
# Routes
# =============================================================================

@app.route('/')
def index():
    machine_id = ""
    if _spotless_app:
        machine_id = _spotless_app.machine_id or ""
    return render_template('index.html', machine_id=machine_id)


@app.route('/session')
def session_page():
    return render_template('session.html')


@app.route('/api/status')
def get_status():
    return jsonify({
        'ready': _spotless_app is not None,
        'machine_id': _spotless_app.machine_id if _spotless_app else None,
        'session_active': _session_runner.is_active if _session_runner else False,
        'current_session': _session_runner.current_session if _session_runner else None,
    })


@app.route('/api/session/start', methods=['POST'])
def start_session():
    data = request.json
    qr_code = data.get('qr_code', '').strip()

    if not qr_code:
        return jsonify({'success': False, 'error': 'QR code is required'}), 400

    if _session_runner and _session_runner.is_active:
        return jsonify({'success': False, 'error': 'A session is already in progress'}), 400

    session_info = validate_qr_code(qr_code, db=_db)

    if not session_info or not session_info.get('session_type'):
        socketio.emit('scan_failed', {
            'message': 'Sorry, QR code validation failed. Please contact management.'
        })
        return jsonify({
            'success': False,
            'error': 'Invalid QR code. Please contact management.',
        }), 400

    session_type = session_info['session_type']
    customer_name = session_info.get('customer_name')
    from_db = session_info.get('from_database', False)
    stages = get_stages(session_type)

    socketio.emit('scan_success', {
        'qr_code': qr_code,
        'session_type': session_type,
        'customer_name': customer_name,
        'from_database': from_db,
        'stages': stages,
    })

    logger.info(f"Starting session: type={session_type}, qr={qr_code}, "
                f"customer={customer_name}, from_db={from_db}")

    _session_runner.start(session_type, qr_code, stages, session_info)

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
    if _session_runner:
        _session_runner.stop()
    return jsonify({'success': True, 'message': 'Session stopped'})


@app.route('/api/session_types')
def get_session_types():
    all_types = get_known_session_types()
    bath = ['small', 'large', 'custdiy', 'medsmall', 'medlarge', 'onlydisinfectant']
    utility = [t for t in all_types if t not in bath]
    return jsonify({'bath_sessions': bath, 'utility_sessions': utility})


# =============================================================================
# WebSocket Events
# =============================================================================

@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')
    emit('connected', {'status': 'connected'})


@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Client disconnected')


@socketio.on('scan_input')
def handle_scan_input(data):
    qr_code = data.get('qr_code', '').strip()
    logger.info(f"Received scan input: {qr_code}")


# =============================================================================
# Database Helper
# =============================================================================

def _get_database():
    """Lazily initialise the DatabaseManager."""
    try:
        from db_manager import DatabaseManager, DEFAULT_DB_CONFIG
        db = DatabaseManager(DEFAULT_DB_CONFIG)
        db.connect()
        logger.info(f"Database connected: {DEFAULT_DB_CONFIG.host}")
        return db
    except Exception as e:
        logger.warning(f"Database not available: {e}")
        return None


# =============================================================================
# Run Server
# =============================================================================

def run_server(host='0.0.0.0', port=5000, debug=False):
    logger.info(f"Starting kiosk server on {host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run_server(debug=True)
