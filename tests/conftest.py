import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_DB_PATH = Path(tempfile.gettempdir()) / "garage_pytest" / "test.db"
TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

for sqlite_file in (TEST_DB_PATH, TEST_DB_PATH.with_name(f"{TEST_DB_PATH.name}-journal")):
    try:
        sqlite_file.unlink(missing_ok=True)
    except OSError:
        pass

os.environ["GARAGE_DATABASE"] = str(TEST_DB_PATH)
os.environ["SECRET_KEY"] = "test-secret-key"

from app import create_app  # noqa: E402
from models.db import get_db  # noqa: E402


@pytest.fixture()
def app():
    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        DATABASE=str(TEST_DB_PATH),
    )

    with flask_app.app_context():
        _reset_database()

    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def booking_date():
    return (date.today() + timedelta(days=7)).isoformat()


@pytest.fixture()
def customer_login(client):
    def _login(identifier="CUST9001"):
        return client.post("/login", data={"identifier": identifier})

    return _login


@pytest.fixture()
def admin_login(client):
    def _login(identifier="ADMIN001"):
        return client.post("/login", data={"identifier": identifier})

    return _login


@pytest.fixture()
def booking_payload(booking_date):
    return {
        "vehicle_number": "GJ05QA9001",
        "brand_model": "Honda Activa",
        "service": "General Service",
        "date": booking_date,
        "customer_phone": "9000000001",
    }


def _reset_database():
    db = get_db()
    db.executescript(
        """
        DELETE FROM audit_logs;
        DELETE FROM bookings;
        DELETE FROM slots;
        DELETE FROM vehicles;
        DELETE FROM customers;
        DELETE FROM admins;
        """
    )
    db.executemany(
        "INSERT INTO admins (id, name, phone) VALUES (?, ?, ?)",
        [
            ("ADMIN001", "Owner", "9898135662"),
            ("ADMIN002", "Manager", ""),
        ],
    )
    db.executemany(
        "INSERT INTO customers (id, name, phone, vehicle) VALUES (?, ?, ?, ?)",
        [
            ("CUST9001", "Test Customer", "9000000001", "GJ05QA9001"),
            ("CUST9002", "Other Customer", "9000000002", "GJ05QA9002"),
        ],
    )
    db.executemany(
        "INSERT INTO vehicles (plate_number, customer_id, brand, model) VALUES (?, ?, ?, ?)",
        [
            ("GJ05QA9001", "CUST9001", "Honda", "Activa"),
            ("GJ05QA9002", "CUST9002", "TVS", "Jupiter"),
        ],
    )
    db.executemany(
        "INSERT INTO slots (date, total) VALUES (?, ?)",
        [
            ((date.today() + timedelta(days=offset)).isoformat(), 5)
            for offset in range(1, 15)
        ],
    )
    db.commit()
