"""
Guest Check-in & Invoice Collection System - Flask Backend
A demo application for managing guest reservations and collecting invoice details.
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, Response
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import os
import csv
import io
import random

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'demo-secret-key-2025')

# Database path
DB_PATH = os.path.join(os.path.dirname(__file__), 'reservations.db')

# Admin credentials (from environment or defaults)
DEMO_EMAIL = os.environ.get('ADMIN_EMAIL', 'dar.duminski@gmail.com')
DEMO_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'temp_pass2912!')


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_building_codes():
    """Get all active building codes."""
    conn = get_db()
    codes = conn.execute('''
        SELECT * FROM building_codes WHERE is_active = 1 ORDER BY display_order
    ''').fetchall()
    conn.close()
    return [dict(c) for c in codes]


def generate_apartment_code():
    """Generate a random 6-digit apartment access code with # at end."""
    return f"{random.randint(100000, 999999)}#"


def can_guest_edit(checkout_date_str):
    """Check if guest can still edit (more than 1 hour before checkout at 11:00)."""
    checkout_date = datetime.strptime(checkout_date_str, '%Y-%m-%d')
    checkout_datetime = checkout_date.replace(hour=11, minute=0, second=0)
    now = datetime.now()
    return now < (checkout_datetime - timedelta(hours=1))




def login_required(f):
    """Decorator to require login for admin routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


# ============== ADMIN ROUTES ==============

@app.route('/admin')
@app.route('/admin/login')
def admin_login():
    """Admin login page."""
    if 'logged_in' in session:
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')


@app.route('/admin/login', methods=['POST'])
def admin_login_post():
    """Handle admin login."""
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    if email == DEMO_EMAIL and password == DEMO_PASSWORD:
        session['logged_in'] = True
        session['email'] = email
        return redirect(url_for('admin_dashboard'))

    flash('Invalid email or password', 'error')
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """Admin dashboard - view all reservations."""
    conn = get_db()
    reservations = conn.execute('''
        SELECT * FROM reservations
        ORDER BY checkin_date DESC
    ''').fetchall()
    conn.close()

    # Get base URL for guest links
    base_url = request.host_url.rstrip('/')

    # Get building codes
    building_codes = get_building_codes()

    return render_template('admin_dashboard.html',
                         reservations=reservations,
                         base_url=base_url,
                         building_codes=building_codes)


@app.route('/admin/logout')
def admin_logout():
    """Logout admin."""
    session.clear()
    return redirect(url_for('admin_login'))


# ============== GUEST ROUTES ==============

@app.route('/guest')
@app.route('/guest/<reservation_number>')
def guest_form(reservation_number=None):
    """Guest form page."""
    # Get reservation number from URL param or path
    if reservation_number is None:
        reservation_number = request.args.get('reservation')

    if not reservation_number:
        return render_template('guest_form.html', error='No reservation number provided')

    conn = get_db()
    reservation = conn.execute('''
        SELECT * FROM reservations WHERE reservation_number = ?
    ''', (reservation_number,)).fetchone()
    conn.close()

    if not reservation:
        return render_template('guest_form.html', error=f'Reservation "{reservation_number}" not found')

    # Check if already submitted
    already_submitted = reservation['guest_submitted_at'] is not None

    # Check if can edit (1h before checkout)
    can_edit = can_guest_edit(reservation['checkout_date'])

    # Get building codes
    building_codes = get_building_codes()

    return render_template('guest_form.html',
                         reservation=reservation,
                         already_submitted=already_submitted,
                         can_edit=can_edit,
                         building_codes=building_codes)


@app.route('/guest/submit', methods=['POST'])
def guest_submit():
    """Handle guest form submission."""
    reservation_number = request.form.get('reservation_number')

    if not reservation_number:
        return jsonify({'success': False, 'error': 'Missing reservation number'}), 400

    conn = get_db()
    reservation = conn.execute('''
        SELECT * FROM reservations WHERE reservation_number = ?
    ''', (reservation_number,)).fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    # Check if editing is allowed (1h before checkout)
    if reservation['guest_submitted_at'] and not can_guest_edit(reservation['checkout_date']):
        conn.close()
        return jsonify({'success': False, 'error': 'Editing is no longer allowed (less than 1 hour before checkout)'}), 403

    # Get invoice type
    invoice_type = request.form.get('invoice_type', '').strip()

    if invoice_type not in ['individual', 'business']:
        conn.close()
        return jsonify({'success': False, 'errors': ['Please select invoice type']}), 400

    errors = []

    # Common required fields
    address = request.form.get('address', '').strip()
    email = request.form.get('email', '').strip()

    if not address:
        errors.append('Address is required')
    if not email:
        errors.append('Email is required')

    # Validate based on invoice type
    if invoice_type == 'individual':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()

        if not first_name:
            errors.append('First name is required')
        if not last_name:
            errors.append('Last name is required')

        company_name = None
        tax_id = None
        vat_eu = None

    else:  # business
        company_name = request.form.get('company_name', '').strip()
        tax_id = request.form.get('tax_id', '').strip()
        vat_eu = request.form.get('vat_eu', '').strip() or None  # Optional

        if not company_name:
            errors.append('Company name is required')
        if not tax_id:
            errors.append('Tax identification number is required')

        first_name = None
        last_name = None

    # Optional field
    special_requests = request.form.get('special_requests', '').strip() or None

    if errors:
        conn.close()
        return jsonify({'success': False, 'errors': errors}), 400

    # Update reservation with guest data
    now = datetime.now().isoformat()

    # If first submission, set guest_submitted_at
    submitted_at = reservation['guest_submitted_at'] or now

    conn.execute('''
        UPDATE reservations SET
            invoice_type = ?,
            first_name = ?,
            last_name = ?,
            company_name = ?,
            tax_id = ?,
            vat_eu = ?,
            address = ?,
            email = ?,
            special_requests = ?,
            guest_submitted_at = ?,
            updated_at = ?
        WHERE reservation_number = ?
    ''', (invoice_type, first_name, last_name, company_name, tax_id, vat_eu,
          address, email, special_requests, submitted_at, now, reservation_number))
    conn.commit()

    # Fetch updated reservation to return access codes
    updated = conn.execute('''
        SELECT * FROM reservations WHERE reservation_number = ?
    ''', (reservation_number,)).fetchone()
    conn.close()

    # Build display name
    if invoice_type == 'individual':
        display_name = f"{first_name} {last_name}"
    else:
        display_name = company_name

    # Get building codes
    building_codes = get_building_codes()

    return jsonify({
        'success': True,
        'building_codes': building_codes,
        'apartment_code': updated['apartment_code'],
        'room_number': updated['room_number'],
        'checkin_date': updated['checkin_date'],
        'checkout_date': updated['checkout_date'],
        'display_name': display_name,
        'invoice_type': invoice_type,
        'email': email,
        'address': address,
        'reservation_number': reservation_number
    })


# ============== API ROUTES ==============

@app.route('/api/reservations')
@login_required
def api_reservations():
    """API endpoint to get all reservations (for admin)."""
    conn = get_db()
    reservations = conn.execute('SELECT * FROM reservations ORDER BY checkin_date DESC').fetchall()
    conn.close()

    return jsonify([dict(r) for r in reservations])


@app.route('/api/reservations/<int:reservation_id>', methods=['PUT'])
@login_required
def update_reservation(reservation_id):
    """Update a reservation (admin only)."""
    conn = get_db()
    reservation = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    data = request.get_json()
    now = datetime.now().isoformat()

    # Build update query based on provided fields
    allowed_fields = [
        'reservation_number', 'room_number', 'apartment_code',
        'checkin_date', 'checkout_date', 'invoice_type',
        'first_name', 'last_name', 'company_name', 'tax_id', 'vat_eu',
        'address', 'email', 'special_requests',
        'service_name', 'amount_paid', 'vat_rate', 'vat_amount',
        'invoice_number', 'invoice_generated_at', 'guest_submitted_at'
    ]

    updates = []
    values = []

    for field in allowed_fields:
        if field in data:
            updates.append(f'{field} = ?')
            values.append(data[field])

    if not updates:
        conn.close()
        return jsonify({'success': False, 'error': 'No fields to update'}), 400

    updates.append('updated_at = ?')
    values.append(now)
    values.append(reservation_id)

    query = f"UPDATE reservations SET {', '.join(updates)} WHERE id = ?"
    conn.execute(query, values)
    conn.commit()

    # Fetch updated reservation
    updated = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()
    conn.close()

    return jsonify({'success': True, 'reservation': dict(updated)})


@app.route('/api/reservations/<int:reservation_id>/reset', methods=['POST'])
@login_required
def reset_reservation(reservation_id):
    """Reset a reservation to pending state (admin testing)."""
    conn = get_db()
    reservation = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    now = datetime.now().isoformat()

    conn.execute('''
        UPDATE reservations SET
            invoice_type = NULL,
            first_name = NULL,
            last_name = NULL,
            company_name = NULL,
            tax_id = NULL,
            vat_eu = NULL,
            address = NULL,
            email = NULL,
            special_requests = NULL,
            service_name = 'Apartment Rental',
            amount_paid = NULL,
            vat_rate = 8.0,
            vat_amount = NULL,
            invoice_generated_at = NULL,
            invoice_number = NULL,
            guest_submitted_at = NULL,
            updated_at = ?
        WHERE id = ?
    ''', (now, reservation_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Reservation reset to pending'})


@app.route('/api/reservations/<int:reservation_id>/generate-invoice', methods=['POST'])
@login_required
def generate_invoice(reservation_id):
    """Generate invoice number and mark as generated (admin only)."""
    conn = get_db()
    reservation = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    if not reservation['guest_submitted_at']:
        conn.close()
        return jsonify({'success': False, 'error': 'Guest has not submitted invoice details yet'}), 400

    data = request.get_json() or {}
    now = datetime.now()

    # Get invoice fields from request or use defaults
    service_name = data.get('service_name', reservation['service_name'] or 'Apartment Rental')
    amount_paid = data.get('amount_paid', reservation['amount_paid'])
    vat_rate = data.get('vat_rate', reservation['vat_rate'] or 8.0)

    if not amount_paid:
        conn.close()
        return jsonify({'success': False, 'error': 'Amount paid is required'}), 400

    # Calculate VAT amount
    vat_amount = round(amount_paid * vat_rate / (100 + vat_rate), 2)

    # Generate invoice number
    year = now.year
    count = conn.execute('SELECT COUNT(*) FROM reservations WHERE invoice_number IS NOT NULL').fetchone()[0]
    invoice_number = f"INV/{year}/{str(count + 1).zfill(3)}"

    conn.execute('''
        UPDATE reservations SET
            service_name = ?,
            amount_paid = ?,
            vat_rate = ?,
            vat_amount = ?,
            invoice_number = ?,
            invoice_generated_at = ?,
            updated_at = ?
        WHERE id = ?
    ''', (service_name, amount_paid, vat_rate, vat_amount, invoice_number, now.isoformat(), now.isoformat(), reservation_id))
    conn.commit()

    updated = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()
    conn.close()

    return jsonify({'success': True, 'reservation': dict(updated)})


@app.route('/api/reservations/export-csv')
@login_required
def export_csv():
    """Export all reservations as CSV."""
    conn = get_db()
    reservations = conn.execute('SELECT * FROM reservations ORDER BY checkin_date DESC').fetchall()
    conn.close()

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    headers = [
        'ID', 'Reservation Number', 'Room', 'Apartment Code',
        'Check-in', 'Check-out', 'Invoice Type',
        'First Name', 'Last Name', 'Company Name', 'Tax ID', 'VAT EU',
        'Address', 'Email', 'Special Requests',
        'Service Name', 'Amount Paid', 'VAT Rate', 'VAT Amount',
        'Invoice Number', 'Invoice Generated', 'Guest Submitted', 'Created', 'Updated'
    ]
    writer.writerow(headers)

    # Write data
    for r in reservations:
        writer.writerow([
            r['id'], r['reservation_number'], r['room_number'], r['apartment_code'],
            r['checkin_date'], r['checkout_date'], r['invoice_type'],
            r['first_name'], r['last_name'], r['company_name'], r['tax_id'], r['vat_eu'],
            r['address'], r['email'], r['special_requests'],
            r['service_name'], r['amount_paid'], r['vat_rate'], r['vat_amount'],
            r['invoice_number'], r['invoice_generated_at'], r['guest_submitted_at'],
            r['created_at'], r['updated_at']
        ])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=reservations_{datetime.now().strftime("%Y%m%d")}.csv'}
    )


@app.route('/api/reservations', methods=['POST'])
@login_required
def create_reservation():
    """Create a new reservation (admin only)."""
    data = request.get_json()
    now = datetime.now().isoformat()

    reservation_number = data.get('reservation_number')
    room_number = data.get('room_number')
    checkin_date = data.get('checkin_date')
    checkout_date = data.get('checkout_date')

    if not all([reservation_number, room_number, checkin_date, checkout_date]):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    conn = get_db()

    # Check if reservation number already exists
    existing = conn.execute('SELECT id FROM reservations WHERE reservation_number = ?', (reservation_number,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation number already exists'}), 400

    apartment_code = generate_apartment_code()

    conn.execute('''
        INSERT INTO reservations (
            reservation_number, room_number, apartment_code,
            checkin_date, checkout_date, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (reservation_number, room_number, apartment_code, checkin_date, checkout_date, now, now))
    conn.commit()

    new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    reservation = conn.execute('SELECT * FROM reservations WHERE id = ?', (new_id,)).fetchone()
    conn.close()

    return jsonify({'success': True, 'reservation': dict(reservation)}), 201


@app.route('/api/reservations/<int:reservation_id>', methods=['DELETE'])
@login_required
def delete_reservation(reservation_id):
    """Delete a reservation (admin only)."""
    conn = get_db()
    reservation = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    conn.execute('DELETE FROM reservations WHERE id = ?', (reservation_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Reservation deleted'})


# ============== BUILDING CODES API ==============

@app.route('/api/building-codes')
def api_building_codes():
    """Get all building codes."""
    codes = get_building_codes()
    return jsonify(codes)


@app.route('/api/building-codes', methods=['POST'])
@login_required
def create_building_code():
    """Create a new building code (admin only)."""
    data = request.get_json()

    name = data.get('name')
    code = data.get('code')
    display_order = data.get('display_order', 0)

    if not name or not code:
        return jsonify({'success': False, 'error': 'Name and code are required'}), 400

    conn = get_db()
    conn.execute('''
        INSERT INTO building_codes (name, code, display_order)
        VALUES (?, ?, ?)
    ''', (name, code, display_order))
    conn.commit()

    new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    building_code = conn.execute('SELECT * FROM building_codes WHERE id = ?', (new_id,)).fetchone()
    conn.close()

    return jsonify({'success': True, 'building_code': dict(building_code)}), 201


@app.route('/api/building-codes/<int:code_id>', methods=['PUT'])
@login_required
def update_building_code(code_id):
    """Update a building code (admin only)."""
    conn = get_db()
    existing = conn.execute('SELECT * FROM building_codes WHERE id = ?', (code_id,)).fetchone()

    if not existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Building code not found'}), 404

    data = request.get_json()

    name = data.get('name', existing['name'])
    code = data.get('code', existing['code'])
    display_order = data.get('display_order', existing['display_order'])
    is_active = data.get('is_active', existing['is_active'])

    conn.execute('''
        UPDATE building_codes SET name = ?, code = ?, display_order = ?, is_active = ?
        WHERE id = ?
    ''', (name, code, display_order, is_active, code_id))
    conn.commit()

    updated = conn.execute('SELECT * FROM building_codes WHERE id = ?', (code_id,)).fetchone()
    conn.close()

    return jsonify({'success': True, 'building_code': dict(updated)})


@app.route('/api/building-codes/<int:code_id>', methods=['DELETE'])
@login_required
def delete_building_code(code_id):
    """Delete a building code (admin only)."""
    conn = get_db()
    existing = conn.execute('SELECT * FROM building_codes WHERE id = ?', (code_id,)).fetchone()

    if not existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Building code not found'}), 404

    conn.execute('DELETE FROM building_codes WHERE id = ?', (code_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Building code deleted'})


# ============== INVOICE SETTINGS API ==============

@app.route('/api/invoice-settings')
@login_required
def get_invoice_settings():
    """Get invoice settings."""
    conn = get_db()
    settings = conn.execute('SELECT * FROM invoice_settings LIMIT 1').fetchone()
    conn.close()

    if settings:
        return jsonify(dict(settings))
    return jsonify({})


@app.route('/api/invoice-settings', methods=['PUT'])
@login_required
def update_invoice_settings():
    """Update invoice settings."""
    data = request.get_json()
    conn = get_db()
    now = datetime.now().isoformat()

    # Build update query
    fields = [
        'issuer_name', 'issuer_address', 'issuer_tax_id', 'issuer_vat_eu',
        'issuer_email', 'issuer_phone', 'issuer_bank_name', 'issuer_bank_account',
        'numbering_pattern', 'rolling_number_current', 'payment_days_due', 'payment_instructions'
    ]

    updates = []
    values = []

    for field in fields:
        if field in data:
            updates.append(f'{field} = ?')
            values.append(data[field])

    if updates:
        updates.append('updated_at = ?')
        values.append(now)

        query = f"UPDATE invoice_settings SET {', '.join(updates)} WHERE id = 1"
        conn.execute(query, values)
        conn.commit()

    settings = conn.execute('SELECT * FROM invoice_settings WHERE id = 1').fetchone()
    conn.close()

    return jsonify({'success': True, 'settings': dict(settings)})


def generate_invoice_number_from_pattern(preview_only=False):
    """Generate the next invoice number based on the configured pattern.
    If preview_only=True, don't increment the rolling number."""
    conn = get_db()
    settings = conn.execute('SELECT * FROM invoice_settings LIMIT 1').fetchone()

    if not settings:
        conn.close()
        return None

    import json
    pattern = json.loads(settings['numbering_pattern'] or '[]')
    rolling_current = settings['rolling_number_current'] or 0

    now = datetime.now()
    parts = []

    for component in pattern:
        comp_type = component.get('type')

        if comp_type == 'fixed':
            parts.append(component.get('value', ''))
        elif comp_type == 'delimiter':
            parts.append(component.get('value', ''))
        elif comp_type == 'year':
            parts.append(str(now.year))
        elif comp_type == 'month':
            parts.append(str(now.month).zfill(2))
        elif comp_type == 'rolling':
            format_spec = component.get('format', '000')
            new_rolling = rolling_current + 1
            if not preview_only:
                # Update rolling number
                conn.execute('UPDATE invoice_settings SET rolling_number_current = ? WHERE id = 1', (new_rolling,))
                conn.commit()
            parts.append(str(new_rolling).zfill(len(format_spec)))

    conn.close()
    return ''.join(parts)


@app.route('/api/next-invoice-number')
@login_required
def get_next_invoice_number():
    """Get the next invoice number (preview, doesn't increment)."""
    invoice_number = generate_invoice_number_from_pattern(preview_only=True)
    return jsonify({'invoice_number': invoice_number})


def check_invoice_number_unique(invoice_number, exclude_reservation_id=None):
    """Check if an invoice number is unique."""
    conn = get_db()
    if exclude_reservation_id:
        existing = conn.execute(
            'SELECT id FROM reservations WHERE invoice_number = ? AND id != ?',
            (invoice_number, exclude_reservation_id)
        ).fetchone()
    else:
        existing = conn.execute(
            'SELECT id FROM reservations WHERE invoice_number = ?',
            (invoice_number,)
        ).fetchone()
    conn.close()
    return existing is None


# ============== INVOICE VERSIONS API ==============

@app.route('/api/reservations/<int:reservation_id>/versions')
@login_required
def get_invoice_versions(reservation_id):
    """Get all invoice versions for a reservation."""
    conn = get_db()
    versions = conn.execute('''
        SELECT * FROM invoice_versions
        WHERE reservation_id = ?
        ORDER BY version_number ASC
    ''', (reservation_id,)).fetchall()
    conn.close()

    return jsonify([dict(v) for v in versions])


@app.route('/api/reservations/<int:reservation_id>/correction', methods=['POST'])
@login_required
def create_invoice_correction(reservation_id):
    """Create an invoice correction."""
    conn = get_db()
    reservation = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    if not reservation['invoice_number']:
        conn.close()
        return jsonify({'success': False, 'error': 'No invoice to correct'}), 400

    data = request.get_json() or {}
    now = datetime.now().isoformat()

    import json

    # Get current version count
    version_count = conn.execute(
        'SELECT COUNT(*) FROM invoice_versions WHERE reservation_id = ?',
        (reservation_id,)
    ).fetchone()[0]

    # If no versions exist, create the original version first
    if version_count == 0:
        original_data = {
            'invoice_type': reservation['invoice_type'],
            'first_name': reservation['first_name'],
            'last_name': reservation['last_name'],
            'company_name': reservation['company_name'],
            'tax_id': reservation['tax_id'],
            'vat_eu': reservation['vat_eu'],
            'address': reservation['address'],
            'service_name': reservation['service_name'],
            'amount_paid': reservation['amount_paid'],
            'vat_rate': reservation['vat_rate'],
            'vat_amount': reservation['vat_amount'],
            'invoice_generated_at': reservation['invoice_generated_at']
        }
        conn.execute('''
            INSERT INTO invoice_versions (reservation_id, version_number, invoice_number, invoice_data, created_at)
            VALUES (?, 1, ?, ?, ?)
        ''', (reservation_id, reservation['invoice_number'], json.dumps(original_data), now))
        version_count = 1

    # Create new correction
    new_version = version_count + 1

    # Generate correction invoice number
    base_number = reservation['invoice_number'].split('_CORRECTED')[0]
    if new_version == 2:
        new_invoice_number = f"{base_number}_CORRECTED"
    else:
        new_invoice_number = f"{base_number}_CORRECTED_{new_version - 1}"

    # Check uniqueness
    if not check_invoice_number_unique(new_invoice_number, reservation_id):
        conn.close()
        return jsonify({'success': False, 'error': 'Invoice number already exists'}), 400

    # Get new invoice data from request
    service_name = data.get('service_name', reservation['service_name'])
    amount_paid = data.get('amount_paid', reservation['amount_paid'])
    vat_rate = data.get('vat_rate', reservation['vat_rate'])

    # Calculate VAT amount
    vat_amount = round(amount_paid * vat_rate / (100 + vat_rate), 2) if amount_paid else 0

    correction_data = {
        'invoice_type': data.get('invoice_type', reservation['invoice_type']),
        'first_name': data.get('first_name', reservation['first_name']),
        'last_name': data.get('last_name', reservation['last_name']),
        'company_name': data.get('company_name', reservation['company_name']),
        'tax_id': data.get('tax_id', reservation['tax_id']),
        'vat_eu': data.get('vat_eu', reservation['vat_eu']),
        'address': data.get('address', reservation['address']),
        'service_name': service_name,
        'amount_paid': amount_paid,
        'vat_rate': vat_rate,
        'vat_amount': vat_amount,
        'invoice_generated_at': now
    }

    # Insert new version
    conn.execute('''
        INSERT INTO invoice_versions (reservation_id, version_number, invoice_number, invoice_data, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (reservation_id, new_version, new_invoice_number, json.dumps(correction_data), now))

    # Update reservation with new invoice data
    conn.execute('''
        UPDATE reservations SET
            invoice_type = ?,
            first_name = ?,
            last_name = ?,
            company_name = ?,
            tax_id = ?,
            vat_eu = ?,
            address = ?,
            service_name = ?,
            amount_paid = ?,
            vat_rate = ?,
            vat_amount = ?,
            invoice_number = ?,
            invoice_generated_at = ?,
            updated_at = ?
        WHERE id = ?
    ''', (
        correction_data['invoice_type'],
        correction_data['first_name'],
        correction_data['last_name'],
        correction_data['company_name'],
        correction_data['tax_id'],
        correction_data['vat_eu'],
        correction_data['address'],
        service_name,
        amount_paid,
        vat_rate,
        vat_amount,
        new_invoice_number,
        now,
        now,
        reservation_id
    ))
    conn.commit()

    updated = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()
    conn.close()

    return jsonify({'success': True, 'reservation': dict(updated), 'version': new_version})


# ============== MAIN ==============

if __name__ == '__main__':
    # Initialize database if needed
    from database import init_db, reset_db
    import sys

    # Check for reset flag
    if len(sys.argv) > 1 and sys.argv[1] == '--reset':
        reset_db()
    else:
        init_db()

    # Get building codes for display
    codes = get_building_codes()
    codes_display = ", ".join([f"{c['name']}: {c['code']}" for c in codes]) if codes else "None configured"

    print("\n" + "="*60)
    print("Guest Check-in & Invoice Collection System")
    print("="*60)
    print("\nAdmin Dashboard: http://localhost:5000/admin")
    print("Demo Guest Links:")
    print("  - Pending: http://localhost:5000/guest?reservation=DEMO-001")
    print("  - Submitted: http://localhost:5000/guest?reservation=DEMO-002")
    print("  - With Invoice: http://localhost:5000/guest?reservation=DEMO-003")
    print("  - Old (14+ days): http://localhost:5000/guest?reservation=DEMO-004")
    print("\nAdmin Credentials:")
    print(f"  Email: {DEMO_EMAIL}")
    print(f"  Password: {DEMO_PASSWORD}")
    print(f"\nBuilding Codes: {codes_display}")
    print("="*60 + "\n")

    app.run(debug=True, port=5000)
