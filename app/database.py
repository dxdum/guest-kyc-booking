"""
Database initialization for Guest Check-in System.
Supports both SQLite (local dev) and PostgreSQL (production).
"""

import os
import random
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

# Check for PostgreSQL DATABASE_URL, fallback to SQLite
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # PostgreSQL mode
    import psycopg2
    from psycopg2.extras import RealDictCursor

    # Render uses postgres:// but psycopg2 needs postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

    DB_TYPE = 'postgresql'
else:
    # SQLite mode (local development)
    import sqlite3
    DB_TYPE = 'sqlite'
    DB_PATH = os.path.join(os.path.dirname(__file__), 'reservations.db')


def get_db():
    """Get database connection based on environment."""
    if DB_TYPE == 'postgresql':
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        # Use timeout to handle Google Drive sync delays
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn


@contextmanager
def get_db_cursor(commit=True):
    """Context manager for database operations."""
    conn = get_db()
    try:
        if DB_TYPE == 'postgresql':
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
        yield cursor
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def dict_from_row(row):
    """Convert database row to dictionary."""
    if row is None:
        return None
    if DB_TYPE == 'postgresql':
        return dict(row) if row else None
    else:
        return dict(row) if row else None


def generate_apartment_code():
    """Generate a random 6-digit apartment access code with # at end."""
    return f"{random.randint(100000, 999999)}#"


def placeholder(index=None):
    """Return correct placeholder for current database type."""
    if DB_TYPE == 'postgresql':
        return '%s'
    else:
        return '?'


def placeholders(count):
    """Return comma-separated placeholders."""
    return ', '.join([placeholder() for _ in range(count)])


# ============== SCHEMA DEFINITIONS ==============

SCHEMA_POSTGRESQL = '''
-- Hosts table (multi-tenant support)
CREATE TABLE IF NOT EXISTS hosts (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,

    -- Profile
    name VARCHAR(255),
    phone VARCHAR(50),

    -- Business type: 'individual' or 'company'
    business_type VARCHAR(20) DEFAULT 'individual',

    -- Business details (for invoices)
    company_name VARCHAR(255),
    tax_id VARCHAR(20),
    vat_eu VARCHAR(20),
    address_street VARCHAR(255),
    address_city VARCHAR(100),
    address_postal VARCHAR(20),
    address_country VARCHAR(2) DEFAULT 'PL',

    -- Bank details (for invoices)
    bank_name VARCHAR(255),
    bank_account VARCHAR(50),

    -- Invoice numbering
    invoice_pattern TEXT DEFAULT '[{"type":"fixed","value":"INV"},{"type":"delimiter","value":"/"},{"type":"year"},{"type":"delimiter","value":"/"},{"type":"rolling","format":"000"}]',
    invoice_rolling_number INTEGER DEFAULT 0,
    payment_days_due INTEGER DEFAULT 0,
    payment_instructions TEXT DEFAULT 'Payment already settled via Booking.com',

    -- Status
    email_verified BOOLEAN DEFAULT FALSE,
    email_verification_token VARCHAR(255),
    email_verification_expires TIMESTAMP,
    password_reset_token VARCHAR(255),
    password_reset_expires TIMESTAMP,

    -- Onboarding
    onboarding_completed BOOLEAN DEFAULT FALSE,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP
);

-- Properties table (apartments/lokale)
CREATE TABLE IF NOT EXISTS properties (
    id SERIAL PRIMARY KEY,
    host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    address VARCHAR(500),

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Building codes (per host)
CREATE TABLE IF NOT EXISTS building_codes (
    id SERIAL PRIMARY KEY,
    host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    display_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reservations (linked to host and optionally property)
CREATE TABLE IF NOT EXISTS reservations (
    id SERIAL PRIMARY KEY,
    host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
    property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,

    reservation_number VARCHAR(100) NOT NULL,
    room_number INTEGER,
    apartment_code VARCHAR(50) NOT NULL,
    checkin_date DATE NOT NULL,
    checkout_date DATE NOT NULL,

    -- Invoice type: 'individual' or 'business'
    invoice_type VARCHAR(20),

    -- Individual guest fields
    first_name VARCHAR(100),
    last_name VARCHAR(100),

    -- Business guest fields
    company_name VARCHAR(255),
    tax_id VARCHAR(20),
    vat_eu VARCHAR(20),

    -- Shared guest fields
    address TEXT,
    email VARCHAR(255),
    special_requests TEXT,

    -- Invoice data (admin filled)
    service_name VARCHAR(255) DEFAULT 'Apartment Rental',
    amount_paid DECIMAL(10,2),
    vat_rate DECIMAL(5,2) DEFAULT 8.0,
    vat_amount DECIMAL(10,2),
    invoice_number VARCHAR(100),
    invoice_generated_at TIMESTAMP,

    -- Timestamps
    guest_submitted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique reservation number per host
    UNIQUE(host_id, reservation_number)
);

-- Invoice versions (for corrections)
CREATE TABLE IF NOT EXISTS invoice_versions (
    id SERIAL PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,

    version_number INTEGER DEFAULT 1,
    invoice_number VARCHAR(100) NOT NULL,
    invoice_data TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_reservations_host ON reservations(host_id);
CREATE INDEX IF NOT EXISTS idx_reservations_number ON reservations(host_id, reservation_number);
CREATE INDEX IF NOT EXISTS idx_building_codes_host ON building_codes(host_id);
CREATE INDEX IF NOT EXISTS idx_properties_host ON properties(host_id);
'''

SCHEMA_SQLITE = '''
-- Hosts table (multi-tenant support)
CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    google_id TEXT UNIQUE,

    -- Profile
    name TEXT,
    phone TEXT,

    -- Business type: 'individual' or 'company'
    business_type TEXT DEFAULT 'individual',

    -- Business details (for invoices)
    company_name TEXT,
    tax_id TEXT,
    vat_eu TEXT,
    address_street TEXT,
    address_city TEXT,
    address_postal TEXT,
    address_country TEXT DEFAULT 'PL',

    -- Bank details (for invoices)
    bank_name TEXT,
    bank_account TEXT,

    -- Invoice numbering
    invoice_pattern TEXT DEFAULT '[{"type":"fixed","value":"INV"},{"type":"delimiter","value":"/"},{"type":"year"},{"type":"delimiter","value":"/"},{"type":"rolling","format":"000"}]',
    invoice_rolling_number INTEGER DEFAULT 0,
    payment_days_due INTEGER DEFAULT 0,
    payment_instructions TEXT DEFAULT 'Payment already settled via Booking.com',

    -- Status
    email_verified INTEGER DEFAULT 0,
    email_verification_token TEXT,
    email_verification_expires TEXT,
    password_reset_token TEXT,
    password_reset_expires TEXT,

    -- Onboarding
    onboarding_completed INTEGER DEFAULT 0,

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT
);

-- Properties table (apartments/lokale)
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,

    name TEXT NOT NULL,
    address TEXT,

    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);

-- Building codes (per host)
CREATE TABLE IF NOT EXISTS building_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,

    name TEXT NOT NULL,
    code TEXT NOT NULL,
    display_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);

-- Reservations (linked to host and optionally property)
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,
    property_id INTEGER,

    reservation_number TEXT NOT NULL,
    room_number INTEGER,
    apartment_code TEXT NOT NULL,
    checkin_date DATE NOT NULL,
    checkout_date DATE NOT NULL,

    -- Invoice type: 'individual' or 'business'
    invoice_type TEXT,

    -- Individual guest fields
    first_name TEXT,
    last_name TEXT,

    -- Business guest fields
    company_name TEXT,
    tax_id TEXT,
    vat_eu TEXT,

    -- Shared guest fields
    address TEXT,
    email TEXT,
    special_requests TEXT,

    -- Invoice data (admin filled)
    service_name TEXT DEFAULT 'Apartment Rental',
    amount_paid REAL,
    vat_rate REAL DEFAULT 8.0,
    vat_amount REAL,
    invoice_number TEXT,
    invoice_generated_at TEXT,

    -- Timestamps
    guest_submitted_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE,
    FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE SET NULL,
    UNIQUE(host_id, reservation_number)
);

-- Invoice versions (for corrections)
CREATE TABLE IF NOT EXISTS invoice_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id INTEGER NOT NULL,

    version_number INTEGER DEFAULT 1,
    invoice_number TEXT NOT NULL,
    invoice_data TEXT NOT NULL,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_reservations_host ON reservations(host_id);
CREATE INDEX IF NOT EXISTS idx_building_codes_host ON building_codes(host_id);
CREATE INDEX IF NOT EXISTS idx_properties_host ON properties(host_id);
'''


def init_db():
    """Initialize the database with schema."""
    conn = get_db()
    cursor = conn.cursor()

    if DB_TYPE == 'postgresql':
        # PostgreSQL: execute entire schema
        cursor.execute(SCHEMA_POSTGRESQL)
    else:
        # SQLite: execute statements one by one
        for statement in SCHEMA_SQLITE.split(';'):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)

    conn.commit()
    conn.close()
    print(f"Database initialized ({DB_TYPE})")


def seed_demo_data(host_id=None):
    """Seed demo data for a specific host or create demo host."""
    from werkzeug.security import generate_password_hash

    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now()
    today = now.date()

    # Create demo host if not provided
    if host_id is None:
        demo_email = 'dar.duminski@gmail.com'
        demo_password = generate_password_hash('pass_2912')

        if DB_TYPE == 'postgresql':
            cursor.execute('''
                INSERT INTO hosts (email, password_hash, name, email_verified, onboarding_completed,
                                   company_name, address_street, address_city, address_postal)
                VALUES (%s, %s, %s, TRUE, TRUE, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                RETURNING id
            ''', (demo_email, demo_password, 'Demo Host', 'Demo Company', 'Demo Street 1', 'Warsaw', '00-001'))
            result = cursor.fetchone()
            host_id = result['id'] if isinstance(result, dict) else result[0]
        else:
            cursor.execute('''
                INSERT OR IGNORE INTO hosts (email, password_hash, name, email_verified, onboarding_completed,
                                             company_name, address_street, address_city, address_postal)
                VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?)
            ''', (demo_email, demo_password, 'Demo Host', 'Demo Company', 'Demo Street 1', 'Warsaw', '00-001'))

            cursor.execute('SELECT id FROM hosts WHERE email = ?', (demo_email,))
            host_id = cursor.fetchone()[0]

    # Check if host already has data
    p = placeholder()
    cursor.execute(f'SELECT COUNT(*) as cnt FROM reservations WHERE host_id = {p}', (host_id,))
    result = cursor.fetchone()
    existing_count = result[0] if isinstance(result, tuple) else result['cnt']

    if existing_count > 0:
        print(f"Host {host_id} already has {existing_count} reservations, skipping seed.")
        conn.close()
        return host_id

    # Seed building codes
    building_codes = [
        ("Main Entrance", "292929#", 1),
        ("Parking Gate", "1234#", 2),
    ]

    for name, code, order in building_codes:
        if DB_TYPE == 'postgresql':
            cursor.execute('''
                INSERT INTO building_codes (host_id, name, code, display_order)
                VALUES (%s, %s, %s, %s)
            ''', (host_id, name, code, order))
        else:
            cursor.execute('''
                INSERT INTO building_codes (host_id, name, code, display_order)
                VALUES (?, ?, ?, ?)
            ''', (host_id, name, code, order))

    # Seed reservations
    seed_reservations = [
        {
            "reservation_number": "DEMO-001",
            "room_number": 1,
            "apartment_code": generate_apartment_code(),
            "checkin_date": str(today + timedelta(days=5)),
            "checkout_date": str(today + timedelta(days=8)),
        },
        {
            "reservation_number": "DEMO-002",
            "room_number": 2,
            "apartment_code": generate_apartment_code(),
            "checkin_date": str(today + timedelta(days=2)),
            "checkout_date": str(today + timedelta(days=5)),
            "invoice_type": "individual",
            "first_name": "Anna",
            "last_name": "Kowalska",
            "address": "ul. Marszalkowska 100, 00-001 Warszawa",
            "email": "anna.kowalska@example.com",
            "guest_submitted_at": str(now - timedelta(days=1)),
        },
        {
            "reservation_number": "DEMO-003",
            "room_number": 3,
            "apartment_code": generate_apartment_code(),
            "checkin_date": str(today - timedelta(days=5)),
            "checkout_date": str(today - timedelta(days=2)),
            "invoice_type": "business",
            "company_name": "Tech Solutions sp. z o.o.",
            "tax_id": "1234567890",
            "vat_eu": "PL1234567890",
            "address": "ul. Nowy Swiat 50, 00-002 Warszawa",
            "email": "invoices@techsolutions.pl",
            "special_requests": "Please include project reference: PRJ-2025-001",
            "guest_submitted_at": str(now - timedelta(days=6)),
            "service_name": "Apartment Rental",
            "amount_paid": 1200.00,
            "vat_rate": 8.0,
            "vat_amount": 224.39,
            "invoice_generated_at": str(now - timedelta(days=1)),
            "invoice_number": "INV/2026/001",
        },
        {
            "reservation_number": "DEMO-004",
            "room_number": 4,
            "apartment_code": generate_apartment_code(),
            "checkin_date": str(today - timedelta(days=20)),
            "checkout_date": str(today - timedelta(days=17)),
            "invoice_type": "individual",
            "first_name": "Jan",
            "last_name": "Nowak",
            "address": "ul. Dluga 15, 00-003 Krakow",
            "email": "jan.nowak@example.com",
            "guest_submitted_at": str(now - timedelta(days=21)),
            "service_name": "Apartment Rental",
            "amount_paid": 800.00,
            "vat_rate": 8.0,
            "vat_amount": 149.59,
            "invoice_generated_at": str(now - timedelta(days=16)),
            "invoice_number": "INV/2026/002",
        },
    ]

    for res in seed_reservations:
        fields = ['host_id', 'reservation_number', 'room_number', 'apartment_code',
                  'checkin_date', 'checkout_date', 'invoice_type', 'first_name', 'last_name',
                  'company_name', 'tax_id', 'vat_eu', 'address', 'email', 'special_requests',
                  'service_name', 'amount_paid', 'vat_rate', 'vat_amount',
                  'invoice_generated_at', 'invoice_number', 'guest_submitted_at']

        values = [host_id]
        for field in fields[1:]:
            values.append(res.get(field))

        placeholders_str = placeholders(len(fields))
        cursor.execute(f'''
            INSERT INTO reservations ({', '.join(fields)})
            VALUES ({placeholders_str})
        ''', values)

    conn.commit()
    conn.close()
    print(f"Demo data seeded for host {host_id}")
    return host_id


def reset_db():
    """Reset the database (drop and recreate)."""
    if DB_TYPE == 'postgresql':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            DROP TABLE IF EXISTS invoice_versions CASCADE;
            DROP TABLE IF EXISTS reservations CASCADE;
            DROP TABLE IF EXISTS building_codes CASCADE;
            DROP TABLE IF EXISTS properties CASCADE;
            DROP TABLE IF EXISTS hosts CASCADE;
        ''')
        conn.commit()
        conn.close()
        print("PostgreSQL tables dropped.")
    else:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print("SQLite database deleted.")

    init_db()
    seed_demo_data()


def get_building_codes(host_id):
    """Get all active building codes for a host."""
    conn = get_db()
    if DB_TYPE == 'postgresql':
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM building_codes
            WHERE host_id = %s AND is_active = TRUE
            ORDER BY display_order
        ''', (host_id,))
    else:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM building_codes
            WHERE host_id = ? AND is_active = 1
            ORDER BY display_order
        ''', (host_id,))

    codes = cursor.fetchall()
    conn.close()
    return [dict(c) for c in codes]


# Import RealDictCursor at module level for get_building_codes
if DB_TYPE == 'postgresql':
    from psycopg2.extras import RealDictCursor


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--reset':
        reset_db()
    elif len(sys.argv) > 1 and sys.argv[1] == '--init':
        init_db()
        seed_demo_data()
    else:
        init_db()
        print("Run with --reset to drop and recreate, or --init to initialize with demo data")
