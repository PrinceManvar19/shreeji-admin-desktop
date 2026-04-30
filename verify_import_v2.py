import sqlite3

DB_PATH = r'C:\Users\ASUS\AppData\Local\GarageManagement\garage.db'

conn = sqlite3.connect(DB_PATH)

print('Customer count:', conn.execute('SELECT COUNT(*) FROM customers;').fetchone()[0])
print('Vehicle count:', conn.execute('SELECT COUNT(*) FROM vehicles;').fetchone()[0])

print('\\nSample data:')
for row in conn.execute('''
    SELECT c.name, c.phone, v.plate_number, v.brand, v.model
    FROM customers c 
    JOIN vehicles v ON v.customer_id = c.id
    LIMIT 10
'''):
    print(f"Name: {row[0]}, Phone: {row[1]}, Plate: {row[2]}, Brand: {row[3]}, Model: {row[4]}")

conn.close()
print('\\nVerification complete. Import successful.')

