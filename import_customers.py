"""
import_customers.py  —  Garage Management System CSV Importer
=============================================================
Reads  Customer Sheet/customers_raw.csv  and inserts rows into the REAL
schema used by this Flask app:

  customers  (id TEXT PK like 'CUST1001', name, phone, vehicle TEXT)
  vehicles   (plate_number TEXT PK, customer_id TEXT FK, brand TEXT, model TEXT)

Key facts about this app's schema (different from a generic importer):
  - customer.id  is TEXT like "CUST1001", NOT an integer autoincrement.
  - customer.vehicle holds the plate_number of the customer's primary vehicle.
  - vehicles.plate_number  is the PRIMARY KEY (no separate integer id).
  - Phone normalisation matches the app's own normalize_phone() exactly.
  - Plate validated against the app's regex: ^[A-Z0-9 -]{4,15}$

Usage
-----
    python import_customers.py --dry-run          # safe preview, no writes
    python import_customers.py                    # real run (auto-detects DB path)
    python import_customers.py --csv "Customer Sheet/customers_raw.csv" --db garage.db

Safe to re-run (idempotent): duplicates are skipped, never doubled.
"""

import argparse
import csv
import os
import re
import sqlite3
import sys

# ── DEFAULTS ──────────────────────────────────────────────────────────────────
DEFAULT_CSV = "Customer Sheet/customers_raw.csv"

_APPDATA = os.getenv("LOCALAPPDATA", "")
DEFAULT_DB = (
    os.path.join(_APPDATA, "GarageManagement", "garage.db")
    if _APPDATA else "garage.db"
)

LOG_EVERY = 500

# Regex strings stored as raw strings to avoid escape warnings
_PLATE_RE = re.compile(r"^[A-Z0-9 \-]{4,15}$")
_NONDIGIT_RE = re.compile(r"\D")


# ── NORMALISATION ─────────────────────────────────────────────────────────────

def normalize_phone(raw):
    """Matches utils/helpers.py normalize_phone() exactly."""
    normalized = (raw or "").strip().replace("+91", "")
    normalized = _NONDIGIT_RE.sub("", normalized)
    if len(normalized) > 10 and normalized.startswith("91"):
        normalized = normalized[-10:]
    return normalized


def clean_plate_raw(raw):
    """
    Strip leading/trailing whitespace and invisible control characters
    (e.g. \\x02 STX found in some CSV cells) before validation.
    """
    return re.sub(r"[\x00-\x1f\x7f]", "", (raw or "").strip())


def normalize_plate(raw):
    """Uppercase, remove spaces/hyphens — produces the PK stored in DB."""
    return re.sub(r"[\s\-]", "", (raw or "").upper())


def parse_vehicle(raw):
    """
    'HERO PASSION PRO' -> ('HERO', 'PASSION PRO')
    'ACTIVA'           -> ('ACTIVA', '')
    ''                 -> ('', '')
    """
    parts = (raw or "").strip().split(None, 1)
    if not parts or not parts[0]:
        return "", ""
    return parts[0].upper(), (parts[1].upper() if len(parts) > 1 else "")


def clean_name(raw):
    return " ".join((raw or "").split())


def is_valid_plate(raw_plate):
    """
    Mirrors customer_model._upsert_vehicle_record validation.
    Validated against the cleaned raw-uppercase plate (spaces & hyphens OK).
    """
    return bool(_PLATE_RE.fullmatch((raw_plate or "").upper()))


# ── CUSTOMER-ID GENERATION ────────────────────────────────────────────────────

def compute_next_id_num(conn):
    """Matches _generate_customer_id() in customer_model.py."""
    rows = conn.execute(
        "SELECT id FROM customers WHERE id LIKE 'CUST%'"
    ).fetchall()
    highest = 1000
    for (cid,) in rows:
        m = re.search(r"(\d+)$", cid or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


# ── CSV READER ────────────────────────────────────────────────────────────────

def open_csv(path):
    return csv.DictReader(
        open(path, encoding="utf-8-sig", newline=""),
        skipinitialspace=True,
    )


HEADER_ALIASES = {
    "name": "name", "customer name": "name", "customer": "name",
    "phone": "phone", "mobile": "phone", "contact": "phone",
    "phone number": "phone",
    "vehicle": "vehicle", "car": "vehicle", "vehicle name": "vehicle",
    "plate_number": "plate_number", "plate": "plate_number",
    "plate number": "plate_number", "registration": "plate_number",
    "vehicle no": "plate_number", "reg": "plate_number",
}


def detect_columns(fieldnames):
    mapping = {}
    for raw in (fieldnames or []):
        key = raw.strip().lower()
        if key in HEADER_ALIASES:
            canonical = HEADER_ALIASES[key]
            if canonical not in mapping:
                mapping[canonical] = raw
    missing = {"name", "phone", "vehicle", "plate_number"} - mapping.keys()
    if missing:
        raise ValueError(
            f"CSV missing required columns: {missing}\n"
            f"Detected headers: {fieldnames}"
        )
    return mapping


# ── DATABASE ──────────────────────────────────────────────────────────────────

def get_connection(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    # Match the app's journal_mode (DELETE avoids OneDrive WAL-file issues)
    conn.execute("PRAGMA journal_mode=DELETE;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ── MAIN IMPORT ───────────────────────────────────────────────────────────────

def run_import(csv_path, db_path, dry_run=False):
    if not os.path.exists(csv_path):
        print(f"[ERROR] CSV not found: {csv_path}")
        sys.exit(1)
    if not dry_run and not os.path.exists(db_path):
        print(f"[ERROR] Database not found: {db_path}")
        print("        Run the Flask app at least once so it creates garage.db first.")
        sys.exit(1)

    print(f"[INFO]  CSV : {csv_path}")
    print(f"[INFO]  DB  : {db_path}{'  (DRY RUN — no writes)' if dry_run else ''}")
    print()

    reader = open_csv(csv_path)
    try:
        col = detect_columns(reader.fieldnames)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    print(f"[INFO]  Column mapping: {col}")
    print()

    conn = get_connection(db_path) if not dry_run else None

    stats = dict(
        total=0,
        customers_added=0, customers_reused=0,
        vehicles_added=0,  vehicles_skipped=0,
        skipped_bad_phone=0, skipped_bad_plate=0,
    )

    # In-memory caches for fast duplicate detection
    phone_to_id = {}  # normalized_phone -> customer_id str
    plate_set   = set()  # normalized plate_number strings

    if conn:
        for row in conn.execute(
            "SELECT id, phone FROM customers WHERE TRIM(COALESCE(phone,'')) <> ''"
        ):
            phone_to_id[row["phone"]] = row["id"]
        for row in conn.execute("SELECT plate_number FROM vehicles"):
            plate_set.add(row["plate_number"])
        next_id_num = compute_next_id_num(conn)
    else:
        next_id_num = 1001  # dry-run counter

    batch = []

    def flush_batch():
        nonlocal next_id_num
        if not batch:
            return

        if dry_run:
            for name, phone, plate_key, brand, model in batch:
                if phone not in phone_to_id:
                    phone_to_id[phone] = f"CUST{next_id_num}"
                    next_id_num += 1
                    stats["customers_added"] += 1
                else:
                    stats["customers_reused"] += 1
                if plate_key not in plate_set:
                    plate_set.add(plate_key)
                    stats["vehicles_added"] += 1
                else:
                    stats["vehicles_skipped"] += 1
            batch.clear()
            return

        with conn:  # auto BEGIN / COMMIT / ROLLBACK
            for name, phone, plate_key, brand, model in batch:
                # ── Customer ─────────────────────────────────────────────
                if phone in phone_to_id:
                    customer_id = phone_to_id[phone]
                    stats["customers_reused"] += 1
                else:
                    customer_id = f"CUST{next_id_num}"
                    next_id_num += 1
                    conn.execute(
                        "INSERT OR IGNORE INTO customers "
                        "(id, name, phone, vehicle) VALUES (?, ?, ?, ?)",
                        (customer_id, name, phone, plate_key),
                    )
                    phone_to_id[phone] = customer_id
                    stats["customers_added"] += 1

                # ── Vehicle ───────────────────────────────────────────────
                if plate_key in plate_set:
                    stats["vehicles_skipped"] += 1
                    continue

                conn.execute(
                    "INSERT OR IGNORE INTO vehicles "
                    "(plate_number, customer_id, brand, model) VALUES (?, ?, ?, ?)",
                    (plate_key, customer_id, brand, model),
                )
                # Keep customers.vehicle pointing to first/primary plate
                conn.execute(
                    "UPDATE customers SET vehicle = ? "
                    "WHERE id = ? AND (vehicle IS NULL OR vehicle = '')",
                    (plate_key, customer_id),
                )
                plate_set.add(plate_key)
                stats["vehicles_added"] += 1

        batch.clear()

    try:
        for raw_row in reader:
            stats["total"] += 1

            name       = clean_name(raw_row.get(col["name"], ""))
            phone      = normalize_phone(raw_row.get(col["phone"], ""))
            raw_plate  = clean_plate_raw(raw_row.get(col["plate_number"], ""))
            brand, model = parse_vehicle(raw_row.get(col["vehicle"], ""))

            # Phone must be exactly 10 digits
            if len(phone) != 10:
                print(
                    f"[WARN]  Row {stats['total']:>6}: skip – bad phone "
                    f"'{raw_row.get(col['phone'], '')}' → '{phone}'"
                )
                stats["skipped_bad_phone"] += 1
                continue

            # Plate must pass the same regex the app uses
            if not is_valid_plate(raw_plate):
                print(
                    f"[WARN]  Row {stats['total']:>6}: skip – bad plate "
                    f"'{raw_plate}' (repr: {repr(raw_plate)})"
                )
                stats["skipped_bad_plate"] += 1
                continue

            plate_key = normalize_plate(raw_plate)
            batch.append((name, phone, plate_key, brand, model))

            if len(batch) >= 200:
                flush_batch()

            if stats["total"] % LOG_EVERY == 0:
                print(
                    f"[INFO]  {stats['total']:>6} rows | "
                    f"+{stats['customers_added']} customers | "
                    f"+{stats['vehicles_added']} vehicles"
                )

        flush_batch()

    finally:
        if conn:
            conn.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 57)
    print("  IMPORT COMPLETE")
    print("=" * 57)
    print(f"  Total CSV rows read          : {stats['total']}")
    print(f"  Skipped – bad phone          : {stats['skipped_bad_phone']}")
    print(f"  Skipped – bad plate format   : {stats['skipped_bad_plate']}")
    print(f"  Customers inserted           : {stats['customers_added']}")
    print(f"  Customers reused (dup phone) : {stats['customers_reused']}")
    print(f"  Vehicles inserted            : {stats['vehicles_added']}")
    print(f"  Vehicles skipped (dup plate) : {stats['vehicles_skipped']}")
    print("=" * 57)
    if dry_run:
        print("  DRY RUN — nothing written to the database.")
        print("=" * 57)


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import customers & vehicles from CSV into garage.db"
    )
    parser.add_argument("--csv", default=DEFAULT_CSV,
                        help=f"Path to CSV (default: {DEFAULT_CSV})")
    parser.add_argument("--db",  default=DEFAULT_DB,
                        help="Path to SQLite DB (default: auto-detected from LOCALAPPDATA)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse only — do NOT write anything to the database")
    args = parser.parse_args()
    run_import(csv_path=args.csv, db_path=args.db, dry_run=args.dry_run)
