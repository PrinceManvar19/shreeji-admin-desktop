import sqlite3

DB_PATH = r'C:\Users\ASUS\AppData\Local\GarageManagement\garage.db'

conn = sqlite3.connect(DB_PATH)
conn.execute('PRAGMA foreign_keys = ON;')

print('Current customers table:')
for row in conn.execute("PRAGMA table_info(customers);"):
    print(row)

print('\\nCurrent vehicles table:')
try:
    for row in conn.execute("PRAGMA table_info(vehicles);"):
        print(row)
except sqlite3.OperationalError:
    print('vehicles table does not exist')

# Add vehicle column if missing
cols = [r[1] for r in conn.execute("PRAGMA table_info(customers);")]
if 'vehicle' not in cols:
    print("\\nAdding vehicle column...")
    conn.execute("ALTER TABLE customers ADD COLUMN vehicle TEXT;")
    print('Added vehicle column.')

# Create vehicles if missing
try:
    conn.execute("SELECT 1 FROM vehicles LIMIT 1;")
except sqlite3.OperationalError:
    print("\\nCreating vehicles table...")
    conn.executescript("""
    CREATE TABLE vehicles (
        plate_number TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        brand TEXT DEFAULT '',
        model TEXT DEFAULT '',
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    """)
    print('Created vehicles table.')

conn.commit()
conn.close()

print('\\nSchema fixed. Re-check:')
conn2 = sqlite3.connect(DB_PATH)
for row in conn2.execute("PRAGMA table_info(customers);"):
    print(row)
for row in conn2.execute("PRAGMA table_info(vehicles);"):
    print(row)
conn2.close()

