"""
=============================================================================
Petgully Spotless - Pet Booking Web Application
=============================================================================
Mobile-friendly booking system for automated pet bathing.

Features:
- Customer registration & login
- Pet registration
- Booking management
- Session parameter customization
- QR code generation for kiosk

Run: python app.py
Access: http://localhost:5001
=============================================================================
"""

import os
import sys
import uuid
import hashlib
import logging
import io
import base64
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, send_file

# Try to import qrcode for QR generation
try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'petgully-booking-secret-key-2026')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Production settings
if os.environ.get('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# =============================================================================
# Database Connection
# =============================================================================
import pymysql
from pymysql.cursors import DictCursor

_db_connection = None

def get_db_config():
    """Get database configuration from environment variables."""
    return {
        'host': os.environ.get('DB_HOST', 'petgully-dbserver.cmzwm2y64qh8.us-east-1.rds.amazonaws.com'),
        'port': int(os.environ.get('DB_PORT', 3306)),
        'user': os.environ.get('DB_USER', 'spotless001'),
        'password': os.environ.get('DB_PASSWORD', 'Batman@686'),
        'database': os.environ.get('DB_NAME', 'petgully_db'),
        'charset': 'utf8mb4',
        'cursorclass': DictCursor,
        'autocommit': True,
    }

def get_db():
    """Get database connection."""
    global _db_connection
    
    try:
        # Check if connection exists and is alive
        if _db_connection is not None:
            try:
                _db_connection.ping(reconnect=True)
                return _db_connection
            except:
                _db_connection = None
        
        # Create new connection
        config = get_db_config()
        _db_connection = pymysql.connect(**config)
        logger.info(f"Database connected: {config['host']}")
        return _db_connection
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None

def get_db_cursor():
    """Get a database cursor."""
    conn = get_db()
    if conn:
        return conn.cursor()
    return None


def init_booking_tables():
    """Initialize booking-related tables."""
    conn = get_db()
    if not conn:
        logger.error("Cannot initialize tables - no database connection")
        return False
    
    try:
        with conn.cursor() as cursor:
            # Customers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password_hash VARCHAR(255),
                    name VARCHAR(100),
                    phone VARCHAR(20),
                    is_admin BOOLEAN DEFAULT FALSE,
                    google_id VARCHAR(255),
                    profile_pic VARCHAR(500),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    INDEX idx_email (email)
                )
            """)
            
            # Pets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pets (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    customer_id INT NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    breed VARCHAR(100),
                    size ENUM('small', 'medium', 'large') DEFAULT 'medium',
                    weight_kg DECIMAL(5,2),
                    age_years INT,
                    photo_url VARCHAR(500),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_customer (customer_id),
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
                )
            """)
            
            # Bookings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    booking_code VARCHAR(20) NOT NULL UNIQUE,
                    customer_id INT NOT NULL,
                    pet_id INT NOT NULL,
                    
                    -- Session parameters
                    session_type VARCHAR(50) DEFAULT 'small',
                    sval INT DEFAULT 120,
                    cval INT DEFAULT 120,
                    dval INT DEFAULT 60,
                    wval INT DEFAULT 60,
                    dryval INT DEFAULT 480,
                    fval INT DEFAULT 60,
                    wt INT DEFAULT 30,
                    ctype INT DEFAULT 100,
                    
                    -- Booking details
                    booking_date DATE,
                    booking_time TIME,
                    status ENUM('pending', 'confirmed', 'completed', 'cancelled') DEFAULT 'pending',
                    payment_status ENUM('pending', 'paid', 'refunded') DEFAULT 'pending',
                    amount DECIMAL(10,2),
                    
                    -- Timestamps
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    
                    INDEX idx_customer (customer_id),
                    INDEX idx_pet (pet_id),
                    INDEX idx_code (booking_code),
                    INDEX idx_date (booking_date),
                    FOREIGN KEY (customer_id) REFERENCES customers(id),
                    FOREIGN KEY (pet_id) REFERENCES pets(id)
                )
            """)
            
            # Create default admin account
            cursor.execute("""
                INSERT IGNORE INTO customers (email, password_hash, name, is_admin)
                VALUES ('admin@petgully.com', %s, 'Admin', TRUE)
            """, (hash_password('admin123'),))
            
            logger.info("Booking tables initialized")
            return True
            
    except Exception as e:
        logger.error(f"Failed to initialize tables: {e}")
        return False


# =============================================================================
# Authentication Helpers
# =============================================================================
def hash_password(password):
    """Hash a password."""
    return hashlib.sha256(password.encode()).hexdigest()


def login_required(f):
    """Decorator for protected routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator for admin-only routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            flash('Admin access required', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def generate_booking_code():
    """Generate unique booking code."""
    return 'PG' + uuid.uuid4().hex[:8].upper()


# =============================================================================
# Routes - Public
# =============================================================================
@app.route('/')
def home():
    """Home page."""
    return render_template('home.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        db = get_db()
        if db:
            try:
                with db.cursor() as cursor:
                    cursor.execute("""
                        SELECT id, name, is_admin FROM customers 
                        WHERE email = %s AND password_hash = %s
                    """, (email, hash_password(password)))
                    user = cursor.fetchone()
                    
                    if user:
                        session['user_id'] = user['id']
                        session['user_name'] = user['name']
                        session['is_admin'] = user['is_admin']
                        session.permanent = True
                        
                        # Update last login
                        cursor.execute("""
                            UPDATE customers SET last_login = NOW() WHERE id = %s
                        """, (user['id'],))
                        
                        flash(f'Welcome back, {user["name"]}!', 'success')
                        return redirect(url_for('dashboard'))
                    else:
                        flash('Invalid email or password', 'error')
            except Exception as e:
                logger.error(f"Login error: {e}")
                flash('Login failed. Please try again.', 'error')
        else:
            flash('Database unavailable', 'error')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Customer registration."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        
        # Validation
        if not name or not email or not password:
            flash('Please fill all required fields', 'error')
            return render_template('register.html')
        
        if password != confirm:
            flash('Passwords do not match', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return render_template('register.html')
        
        db = get_db()
        if db:
            try:
                with db.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO customers (email, password_hash, name, phone)
                        VALUES (%s, %s, %s, %s)
                    """, (email, hash_password(password), name, phone))
                    
                    flash('Registration successful! Please login.', 'success')
                    return redirect(url_for('login'))
                    
            except Exception as e:
                if 'Duplicate' in str(e):
                    flash('Email already registered', 'error')
                else:
                    logger.error(f"Registration error: {e}")
                    flash('Registration failed. Please try again.', 'error')
        else:
            flash('Database unavailable', 'error')
    
    return render_template('register.html')


@app.route('/logout')
def logout():
    """Logout."""
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('home'))


# =============================================================================
# Routes - Dashboard
# =============================================================================
@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard - show pets and bookings."""
    db = get_db()
    pets = []
    bookings = []
    
    if db:
        try:
            with db.cursor() as cursor:
                # Get user's pets
                cursor.execute("""
                    SELECT * FROM pets WHERE customer_id = %s ORDER BY created_at DESC
                """, (session['user_id'],))
                pets = cursor.fetchall()
                
                # Get recent bookings
                cursor.execute("""
                    SELECT b.*, p.name as pet_name 
                    FROM bookings b 
                    JOIN pets p ON b.pet_id = p.id
                    WHERE b.customer_id = %s 
                    ORDER BY b.created_at DESC LIMIT 10
                """, (session['user_id'],))
                bookings = cursor.fetchall()
                
        except Exception as e:
            logger.error(f"Dashboard error: {e}")
    
    return render_template('dashboard.html', pets=pets, bookings=bookings)


# =============================================================================
# Routes - Pets
# =============================================================================
@app.route('/pets/add', methods=['GET', 'POST'])
@login_required
def add_pet():
    """Add a new pet."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        breed = request.form.get('breed', '').strip()
        size = request.form.get('size', 'medium')
        weight = request.form.get('weight', 0)
        age = request.form.get('age', 0)
        notes = request.form.get('notes', '').strip()
        
        if not name:
            flash('Pet name is required', 'error')
            return render_template('add_pet.html')
        
        db = get_db()
        if db:
            try:
                with db.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO pets (customer_id, name, breed, size, weight_kg, age_years, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (session['user_id'], name, breed, size, weight or None, age or None, notes))
                    
                    flash(f'{name} has been registered!', 'success')
                    return redirect(url_for('dashboard'))
                    
            except Exception as e:
                logger.error(f"Add pet error: {e}")
                flash('Failed to add pet', 'error')
    
    return render_template('add_pet.html')


@app.route('/pets/<int:pet_id>')
@login_required
def view_pet(pet_id):
    """View pet details."""
    db = get_db()
    pet = None
    bookings = []
    
    if db:
        try:
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM pets WHERE id = %s AND customer_id = %s
                """, (pet_id, session['user_id']))
                pet = cursor.fetchone()
                
                if pet:
                    cursor.execute("""
                        SELECT * FROM bookings WHERE pet_id = %s ORDER BY created_at DESC
                    """, (pet_id,))
                    bookings = cursor.fetchall()
                    
        except Exception as e:
            logger.error(f"View pet error: {e}")
    
    if not pet:
        flash('Pet not found', 'error')
        return redirect(url_for('dashboard'))
    
    return render_template('view_pet.html', pet=pet, bookings=bookings)


# =============================================================================
# Routes - Booking
# =============================================================================
@app.route('/book/<int:pet_id>', methods=['GET', 'POST'])
@login_required
def book_session(pet_id):
    """Book a grooming session."""
    db = get_db()
    pet = None
    
    if db:
        try:
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM pets WHERE id = %s AND customer_id = %s
                """, (pet_id, session['user_id']))
                pet = cursor.fetchone()
        except Exception as e:
            logger.error(f"Book session error: {e}")
    
    if not pet:
        flash('Pet not found', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        # Get booking details
        session_type = request.form.get('session_type', 'small')
        booking_date = request.form.get('booking_date')
        booking_time = request.form.get('booking_time')
        
        # Get custom parameters
        sval = int(request.form.get('sval', 120))
        cval = int(request.form.get('cval', 120))
        dval = int(request.form.get('dval', 60))
        wval = int(request.form.get('wval', 60))
        dryval = int(request.form.get('dryval', 480))
        ctype = int(request.form.get('ctype', 100))
        
        # Calculate price based on session type
        prices = {
            'small': 299, 'large': 399, 'medsmall': 349, 
            'medlarge': 449, 'custdiy': 249
        }
        amount = prices.get(session_type, 299)
        
        try:
            with db.cursor() as cursor:
                booking_code = generate_booking_code()
                
                cursor.execute("""
                    INSERT INTO bookings 
                    (booking_code, customer_id, pet_id, session_type,
                     sval, cval, dval, wval, dryval, ctype,
                     booking_date, booking_time, amount)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (booking_code, session['user_id'], pet_id, session_type,
                      sval, cval, dval, wval, dryval, ctype,
                      booking_date, booking_time, amount))
                
                # Also add to session_config for kiosk lookup
                cursor.execute("""
                    INSERT INTO session_config 
                    (mobile_number, customer_name, session_type,
                     sval, cval, dval, wval, dryval, fval, wt, stval, msgval, tdry, pr, ctype)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 60, 30, 10, 10, 30, 20, %s)
                    ON DUPLICATE KEY UPDATE
                    session_type = VALUES(session_type),
                    sval = VALUES(sval), cval = VALUES(cval),
                    dval = VALUES(dval), wval = VALUES(wval),
                    dryval = VALUES(dryval), ctype = VALUES(ctype)
                """, (booking_code, pet['name'], session_type,
                      sval, cval, dval, wval, dryval, ctype))
                
                flash(f'Booking confirmed! Code: {booking_code}', 'success')
                return redirect(url_for('booking_confirmation', code=booking_code))
                
        except Exception as e:
            logger.error(f"Booking error: {e}")
            flash('Booking failed. Please try again.', 'error')
    
    # Default parameters based on pet size
    defaults = {
        'small': {'sval': 120, 'cval': 120, 'dryval': 480},
        'medium': {'sval': 135, 'cval': 135, 'dryval': 540},
        'large': {'sval': 150, 'cval': 150, 'dryval': 600},
    }
    params = defaults.get(pet['size'], defaults['medium'])
    
    return render_template('book_session.html', pet=pet, defaults=params)


@app.route('/booking/<code>')
@login_required
def booking_confirmation(code):
    """Booking confirmation page."""
    db = get_db()
    booking = None
    
    if db:
        try:
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT b.*, p.name as pet_name, p.breed, p.size
                    FROM bookings b
                    JOIN pets p ON b.pet_id = p.id
                    WHERE b.booking_code = %s AND b.customer_id = %s
                """, (code, session['user_id']))
                booking = cursor.fetchone()
        except Exception as e:
            logger.error(f"Confirmation error: {e}")
            flash(f'Error loading booking: {e}', 'error')
    
    if not booking:
        flash('Booking not found', 'error')
        return redirect(url_for('dashboard'))
    
    # Generate QR code as base64
    qr_image = None
    if QRCODE_AVAILABLE:
        try:
            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(booking['booking_code'])
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            qr_image = base64.b64encode(buffer.getvalue()).decode()
        except Exception as e:
            logger.error(f"QR generation error: {e}")
    
    return render_template('booking_confirmation.html', booking=booking, qr_image=qr_image)


@app.route('/qr/<code>')
def generate_qr(code):
    """Generate QR code image for a booking code."""
    if not QRCODE_AVAILABLE:
        return "QR code library not installed", 500
    
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(code)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return send_file(buffer, mimetype='image/png')
    except Exception as e:
        return f"Error: {e}", 500


# =============================================================================
# Routes - Admin
# =============================================================================
@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin dashboard."""
    db = get_db()
    stats = {}
    recent_bookings = []
    
    if db:
        try:
            with db.cursor() as cursor:
                # Stats
                cursor.execute("SELECT COUNT(*) as count FROM customers WHERE is_admin = FALSE")
                stats['customers'] = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM pets")
                stats['pets'] = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE status = 'pending'")
                stats['pending'] = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE status = 'completed'")
                stats['completed'] = cursor.fetchone()['count']
                
                # Recent bookings
                cursor.execute("""
                    SELECT b.*, c.name as customer_name, p.name as pet_name
                    FROM bookings b
                    JOIN customers c ON b.customer_id = c.id
                    JOIN pets p ON b.pet_id = p.id
                    ORDER BY b.created_at DESC LIMIT 20
                """)
                recent_bookings = cursor.fetchall()
                
        except Exception as e:
            logger.error(f"Admin dashboard error: {e}")
    
    return render_template('admin/dashboard.html', stats=stats, bookings=recent_bookings)


# =============================================================================
# API Endpoints
# =============================================================================
@app.route('/api/pets')
@login_required
def api_get_pets():
    """Get user's pets."""
    db = get_db()
    if db:
        try:
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT id, name, breed, size, photo_url 
                    FROM pets WHERE customer_id = %s
                """, (session['user_id'],))
                pets = cursor.fetchall()
                return jsonify({'success': True, 'pets': pets})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    return jsonify({'success': False, 'error': 'Database unavailable'})


@app.route('/api/booking/<code>')
def api_get_booking(code):
    """Get booking details (for kiosk lookup)."""
    db = get_db()
    if db:
        try:
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT b.*, p.name as pet_name, c.name as customer_name
                    FROM bookings b
                    JOIN pets p ON b.pet_id = p.id
                    JOIN customers c ON b.customer_id = c.id
                    WHERE b.booking_code = %s
                """, (code,))
                booking = cursor.fetchone()
                
                if booking:
                    return jsonify({
                        'success': True,
                        'booking': {
                            'code': booking['booking_code'],
                            'pet_name': booking['pet_name'],
                            'customer_name': booking['customer_name'],
                            'session_type': booking['session_type'],
                            'sval': booking['sval'],
                            'cval': booking['cval'],
                            'dval': booking['dval'],
                            'wval': booking['wval'],
                            'dryval': booking['dryval'],
                        }
                    })
                return jsonify({'success': False, 'error': 'Booking not found'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    return jsonify({'success': False, 'error': 'Database unavailable'})


# =============================================================================
# Error Handlers
# =============================================================================
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error='Page not found'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error='Server error'), 500


# =============================================================================
# Main
# =============================================================================
if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  Petgully Spotless - Booking Application")
    print("=" * 60)
    
    # Initialize database tables
    print("\nInitializing database tables...")
    if init_booking_tables():
        print("Database tables ready!")
    else:
        print("WARNING: Database tables not initialized")
    
    # Get port from environment (for production) or default to 5001
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV', 'development') != 'production'
    
    print(f"\nStarting server on http://localhost:{port}")
    print(f"Environment: {'Production' if not debug else 'Development'}")
    print("=" * 60 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
