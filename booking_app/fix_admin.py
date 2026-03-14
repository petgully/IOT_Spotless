"""Fix admin password."""
import hashlib
import sys
sys.path.insert(0, '../raspberry_pi')
from db_manager import DatabaseManager, DEFAULT_DB_CONFIG

db = DatabaseManager(DEFAULT_DB_CONFIG)
if db.connect():
    print('DB Connected!')
    
    pwd = hashlib.sha256('admin123'.encode()).hexdigest()
    print(f'Password hash: {pwd}')
    
    with db._connection.cursor() as cursor:
        # Update admin password
        cursor.execute('''
            UPDATE customers SET password_hash = %s WHERE email = %s
        ''', (pwd, 'admin@petgully.com'))
        
        print('Admin password set to: admin123')
        print('Email: admin@petgully.com')
        
        # Verify
        cursor.execute('SELECT id, email, name, is_admin FROM customers WHERE email = %s', ('admin@petgully.com',))
        user = cursor.fetchone()
        if user:
            print(f"Verified: {user['email']} (Admin: {user['is_admin']})")
    
    db.disconnect()
    print('\nNow try logging in at http://localhost:5001/login')
else:
    print('DB Connection Failed')
