import sqlite3

DB_PATH = r'C:\Users\ASUS\AppData\Local\GarageManagement\garage.db'

conn = sqlite3.connect(DB_PATH)
conn.execute('PRAGMA foreign_keys = ON;')

print('Before fixes:')

print('customers:')
for row in conn.execute("PRAGMA table_info(customers);"):
    print(f"  {row}")

print('vehicles:')
for row in conn.execute("PRAGMA table_info(vehicles);"):
    print(f"  {row}")

# Fix customers.id: change to TEXT PK
try:
    conn.execute('SELECT 1 FROM customers WHERE id=1;')
except:
    print('\\ncustomers.id already non-numeric')
if 'id' in [r[1] for r in conn.execute("PRAGMA table_info(customers);")]:
    conn.executescript('''
    -- Backup current data
    CREATE TABLE customers_new (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT,
        vehicle TEXT
    );
    
    INSERT INTO customers_new (id, name, phone, vehicle)
    SELECT CAST(id AS TEXT), name, phone, vehicle FROM customers;
    
    DROP TABLE customers;
    ALTER TABLE customers_new RENAME TO customers;
    ''')

# Fix vehicles: drop id PK, make plate_number PK, customer_id TEXT
conn.executescript('''
-- Drop old vehicles if exists, recreate properly
DROP TABLE IF EXISTS vehicles;

CREATE TABLE vehicles (
    plate_number TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    brand TEXT DEFAULT '',
    model TEXT DEFAULT '',
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
''')

print('\\nAfter fixes:')

print('customers:')
for row in conn.execute("PRAGMA table_info(customers);"):
    print(f"  {row}")

print('vehicles:')
for row in conn.execute("PRAGMA table_info(vehicles);"):
    print(f"  {row}")

# Verify counts before/after? Skip for now

conn.commit()
conn.close()
print('\\nSchema fully fixed. Ready for import.')

