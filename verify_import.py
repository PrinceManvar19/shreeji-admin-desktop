import sqlite3

DB_PATH = r'C:\Users\ASUS\AppData\Local\GarageManagement\garage.db'

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print('Customer count:', conn.execute('SELECT COUNT(*) FROM customers;').fetchone()[0])
print('Vehicle count:', conn.execute('SELECT COUNT(*) FROM vehicles;').fetchone()[0])

print('\\nSample data:')
for row in conn.execute('''
    SELECT c.name, c.phone, v.plate_number, v.brand, v.model
    FROM customers c 
    JOIN vehicles v ON v.customer_id = c.id
    LIMIT 10
'''):
    print(row)

conn.close()

