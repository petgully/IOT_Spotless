"""Check database connection and tables."""
from db_manager import DatabaseManager, DEFAULT_DB_CONFIG

db = DatabaseManager(DEFAULT_DB_CONFIG)
print('Connecting to database...')

if db.connect():
    print('SUCCESS: Connected!')
    
    with db._connection.cursor() as cursor:
        # Check tables
        print('\n--- Tables in petgully_db ---')
        cursor.execute('SHOW TABLES')
        tables = cursor.fetchall()
        for t in tables:
            print(f'  - {list(t.values())[0]}')
        
        # Check customers table
        print('\n--- Customers Table ---')
        try:
            cursor.execute('SELECT id, email, name, is_admin FROM customers LIMIT 5')
            customers = cursor.fetchall()
            for c in customers:
                print(f"  ID: {c['id']}, Email: {c['email']}, Name: {c['name']}, Admin: {c['is_admin']}")
            
            if not customers:
                print('  (No customers found - creating admin account...)')
                # Create admin with password 'admin123'
                import hashlib
                pwd_hash = hashlib.sha256('admin123'.encode()).hexdigest()
                cursor.execute("""
                    INSERT INTO customers (email, password_hash, name, is_admin)
                    VALUES ('admin@petgully.com', %s, 'Admin', TRUE)
                    ON DUPLICATE KEY UPDATE password_hash = %s
                """, (pwd_hash, pwd_hash))
                print('  Admin account created/updated!')
                print(f'  Email: admin@petgully.com')
                print(f'  Password: admin123')
        except Exception as e:
            print(f'  Error: {e}')
            
    db.disconnect()
else:
    print('FAILED: Could not connect')
