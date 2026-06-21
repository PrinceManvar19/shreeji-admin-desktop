import os

import psycopg2
from dotenv import load_dotenv


load_dotenv(override=True)
url = os.getenv("DATABASE_URL")
conn = psycopg2.connect(url, connect_timeout=10)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM bookings")
print("Bookings in new DB:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM customers")
print("Customers in new DB:", cur.fetchone()[0])
conn.close()
