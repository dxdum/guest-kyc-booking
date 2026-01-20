"""
Database initialization and seeding for Guest Check-in System.
"""

import sqlite3
import os
from datetime import datetime, timedelta
import random
import json

DB_PATH = os.path.join(os.path.dirname(__file__), 'reservations.db')


def generate_apartment_code():
    """Generate a random 6-digit apartment access code with # at end."""
    return f"{random.randint(100000, 999999)}#"


def init_db():
    """Initialize the database with schema and seed data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create reservations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reservation_number TEXT UNIQUE NOT NULL,
            room_number INTEGER NOT NULL,
            apartment_code TEXT NOT NULL,
            checkin_date DATE NOT NULL,
            checkout_date DATE NOT NULL,

            -- Invoice type: 'individual' or 'business'
            invoice_type TEXT,

            -- Individual fields
            first_name TEXT,
            last_name TEXT,

            -- Business fields
            company_name TEXT,
            tax_id TEXT,
            vat_eu TEXT,

            -- Shared fields
            address TEXT,
            email TEXT,
            special_requests TEXT,

            -- Invoice data (admin filled)
            service_name TEXT DEFAULT 'Apartment Rental',
            amount_paid REAL,
            vat_rate REAL DEFAULT 8.0,
            vat_amount REAL,
            invoice_generated_at TIMESTAMP,
            invoice_number TEXT,

            -- Status
            guest_submitted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create building_codes table for configurable building access codes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS building_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create invoice_settings table for issuer details and numbering configuration
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoice_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            -- Issuer details
            issuer_name TEXT,
            issuer_address TEXT,
            issuer_tax_id TEXT,
            issuer_vat_eu TEXT,
            issuer_email TEXT,
            issuer_phone TEXT,
            issuer_bank_name TEXT,
            issuer_bank_account TEXT,
            -- Invoice numbering configuration (JSON format for flexibility)
            -- Example: [{"type":"fixed","value":"FAK"},{"type":"delimiter","value":"-"},{"type":"year"},{"type":"delimiter","value":"-"},{"type":"month"},{"type":"delimiter","value":"/"},{"type":"rolling","format":"000"}]
            numbering_pattern TEXT DEFAULT '[{"type":"fixed","value":"INV"},{"type":"delimiter","value":"/"},{"type":"year"},{"type":"delimiter","value":"/"},{"type":"rolling","format":"000"}]',
            rolling_number_current INTEGER DEFAULT 0,
            payment_days_due INTEGER DEFAULT 0,
            payment_instructions TEXT DEFAULT 'Payment already settled via Booking.com',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create invoice_versions table for tracking invoice corrections
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoice_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reservation_id INTEGER NOT NULL,
            version_number INTEGER DEFAULT 1,
            invoice_number TEXT NOT NULL,
            invoice_data TEXT NOT NULL,  -- JSON snapshot of invoice at time of creation
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reservation_id) REFERENCES reservations(id)
        )
    ''')

    # Ensure invoice_settings has at least one row
    existing_settings = cursor.execute('SELECT COUNT(*) FROM invoice_settings').fetchone()[0]
    if existing_settings == 0:
        cursor.execute('''
            INSERT INTO invoice_settings (issuer_name, issuer_address)
            VALUES ('Your Company Name', 'Your Address')
        ''')

    # Check if we need to seed data
    existing = cursor.execute('SELECT COUNT(*) FROM reservations').fetchone()[0]

    if existing == 0:
        seed_data(cursor)
        print("Database seeded with demo data.")
    else:
        print(f"Database already has {existing} reservations.")

    conn.commit()
    conn.close()


def seed_data(cursor):
    """Seed the database with demo reservations and building codes."""
    now = datetime.now()
    today = now.date()

    # Seed building codes
    building_codes = [
        ("Main Entrance", "292929#", 1),
        ("Parking Gate", "1234#", 2),
    ]

    for name, code, order in building_codes:
        cursor.execute('''
            INSERT INTO building_codes (name, code, display_order)
            VALUES (?, ?, ?)
        ''', (name, code, order))

    # Seed reservations
    seed_reservations = [
        # Case 1: Pending - no details submitted yet
        {
            "reservation_number": "DEMO-001",
            "room_number": 1,
            "apartment_code": generate_apartment_code(),
            "checkin_date": str(today + timedelta(days=5)),
            "checkout_date": str(today + timedelta(days=8)),
            "invoice_type": None,
            "guest_submitted_at": None,
        },
        # Case 2: Submitted - details provided, upcoming stay
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
        # Case 3: Past checkout, invoice generated (within 7 days)
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
            "invoice_number": "INV/2025/001",
        },
        # Case 4: Past checkout 14+ days ago (user can't download, admin has it)
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
            "invoice_number": "INV/2025/002",
        },
    ]

    for res in seed_reservations:
        cursor.execute('''
            INSERT INTO reservations (
                reservation_number, room_number, apartment_code,
                checkin_date, checkout_date, invoice_type,
                first_name, last_name, company_name, tax_id, vat_eu,
                address, email, special_requests,
                service_name, amount_paid, vat_rate, vat_amount,
                invoice_generated_at, invoice_number,
                guest_submitted_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            res['reservation_number'],
            res['room_number'],
            res['apartment_code'],
            res['checkin_date'],
            res['checkout_date'],
            res.get('invoice_type'),
            res.get('first_name'),
            res.get('last_name'),
            res.get('company_name'),
            res.get('tax_id'),
            res.get('vat_eu'),
            res.get('address'),
            res.get('email'),
            res.get('special_requests'),
            res.get('service_name'),
            res.get('amount_paid'),
            res.get('vat_rate'),
            res.get('vat_amount'),
            res.get('invoice_generated_at'),
            res.get('invoice_number'),
            res.get('guest_submitted_at'),
            now.isoformat(),
            now.isoformat()
        ))


def reset_db():
    """Reset the database (drop and recreate)."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Database deleted.")
    init_db()


def get_building_codes():
    """Get all active building codes."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    codes = conn.execute('''
        SELECT * FROM building_codes WHERE is_active = 1 ORDER BY display_order
    ''').fetchall()
    conn.close()
    return [dict(c) for c in codes]


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--reset':
        reset_db()
    else:
        init_db()
