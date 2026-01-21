"""
Guest Check-in & Invoice Collection System - Flask Backend
Multi-tenant application for managing guest reservations and collecting invoice details.
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, Response
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os
import csv
import io
import json
import secrets
import uuid

from database import (
    get_db, get_building_codes, generate_apartment_code,
    DB_TYPE, placeholder, placeholders, init_db, seed_demo_data
)
from email_service import send_verification_email

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'demo-secret-key-2025')

# For backwards compatibility - demo credentials fallback
DEMO_EMAIL = os.environ.get('ADMIN_EMAIL', 'dar.duminski@gmail.com')
DEMO_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'pass_2912')


def get_current_host_id():
    """Get the current logged-in host's ID from session."""
    return session.get('host_id')


def can_guest_edit(checkout_date_str):
    """Check if guest can still edit (more than 1 hour before checkout at 11:00)."""
    if isinstance(checkout_date_str, str):
        checkout_date = datetime.strptime(checkout_date_str, '%Y-%m-%d')
    else:
        checkout_date = checkout_date_str
    checkout_datetime = datetime.combine(checkout_date, datetime.min.time()).replace(hour=11, minute=0, second=0)
    now = datetime.now()
    return now < (checkout_datetime - timedelta(hours=1))


def login_required(f):
    """Decorator to require login for admin routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'host_id' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


def execute_query(cursor, query, params=None):
    """Execute a query with proper placeholder substitution."""
    if DB_TYPE == 'postgresql':
        # PostgreSQL uses %s
        query = query.replace('?', '%s')
    cursor.execute(query, params or ())
    return cursor


def dict_row(row):
    """Convert a database row to dictionary."""
    if row is None:
        return None
    return dict(row)


# ============== ADMIN ROUTES ==============

@app.route('/admin')
@app.route('/admin/login')
def admin_login():
    """Admin login page."""
    if 'host_id' in session:
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')


@app.route('/admin/login', methods=['POST'])
def admin_login_post():
    """Handle admin login."""
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM hosts WHERE LOWER(email) = %s', (email,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM hosts WHERE LOWER(email) = ?', (email,))

    host = cursor.fetchone()
    conn.close()

    if host:
        host_dict = dict(host)
        # Check password hash
        if host_dict.get('password_hash') and check_password_hash(host_dict['password_hash'], password):
            # Check if email is verified
            email_verified = host_dict.get('email_verified')
            if DB_TYPE == 'sqlite':
                email_verified = bool(email_verified)

            if not email_verified:
                # Redirect to verification page
                session['pending_verification_email'] = host_dict['email']
                session['verification_token'] = host_dict.get('email_verification_token')
                flash('Please verify your email before logging in', 'error')
                return redirect(url_for('verify_email_pending'))

            session['host_id'] = host_dict['id']
            session['email'] = host_dict['email']
            session['host_name'] = host_dict.get('name') or host_dict['email'].split('@')[0]

            # Update last login
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            execute_query(cursor, 'UPDATE hosts SET last_login_at = ? WHERE id = ?', (now, host_dict['id']))
            conn.commit()
            conn.close()

            # Check if onboarding is completed
            if not host_dict.get('onboarding_completed'):
                return redirect(url_for('admin_onboarding'))

            return redirect(url_for('admin_dashboard'))

    flash('Invalid email or password', 'error')
    return redirect(url_for('admin_login'))


@app.route('/register', methods=['GET'])
def register():
    """Registration page."""
    if 'host_id' in session:
        return redirect(url_for('admin_dashboard'))
    return render_template('register.html')


@app.route('/register', methods=['POST'])
def register_post():
    """Handle new host registration."""
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    password_confirm = request.form.get('password_confirm', '')

    # Validation
    if not email or not password:
        flash('Email and password are required', 'error')
        return redirect(url_for('register'))

    if password != password_confirm:
        flash('Passwords do not match', 'error')
        return redirect(url_for('register'))

    if len(password) < 6:
        flash('Password must be at least 6 characters', 'error')
        return redirect(url_for('register'))

    # Check if email already exists
    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id, email_verified FROM hosts WHERE LOWER(email) = %s', (email,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT id, email_verified FROM hosts WHERE LOWER(email) = ?', (email,))

    existing = cursor.fetchone()
    if existing:
        conn.close()
        flash('An account with this email already exists', 'error')
        return redirect(url_for('register'))

    # Generate verification token
    verification_token = secrets.token_urlsafe(32)
    token_expires = (datetime.now() + timedelta(hours=24)).isoformat()

    # Create new host (unverified)
    password_hash = generate_password_hash(password)
    now = datetime.now().isoformat()

    if DB_TYPE == 'postgresql':
        cursor.execute('''
            INSERT INTO hosts (email, password_hash, email_verified, email_verification_token,
                              email_verification_expires, created_at, updated_at)
            VALUES (%s, %s, FALSE, %s, %s, %s, %s)
            RETURNING id
        ''', (email, password_hash, verification_token, token_expires, now, now))
        result = cursor.fetchone()
        host_id = result['id'] if isinstance(result, dict) else result[0]
    else:
        cursor.execute('''
            INSERT INTO hosts (email, password_hash, email_verified, email_verification_token,
                              email_verification_expires, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?, ?, ?)
        ''', (email, password_hash, verification_token, token_expires, now, now))
        host_id = cursor.lastrowid

    conn.commit()
    conn.close()

    # Generate verification URL
    verification_url = url_for('verify_email_confirm', token=verification_token, _external=True)

    # Send verification email
    email_result = send_verification_email(email, verification_url)

    # Store email in session for verification page
    session['pending_verification_email'] = email
    session['verification_token'] = verification_token  # Fallback for dev mode display
    session['email_sent'] = email_result.get('success', False)

    return redirect(url_for('verify_email_pending'))


@app.route('/verify-email')
def verify_email_pending():
    """Show verification pending page."""
    email = session.get('pending_verification_email')
    token = session.get('verification_token')  # For dev mode

    if not email:
        return redirect(url_for('register'))

    # Generate verification URL for dev mode display
    verification_url = url_for('verify_email_confirm', token=token, _external=True) if token else None

    return render_template('verify_email.html', email=email, verification_url=verification_url)


@app.route('/verify-email/<token>')
def verify_email_confirm(token):
    """Confirm email verification."""
    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT id, email, email_verification_expires FROM hosts
            WHERE email_verification_token = %s
        ''', (token,))
    else:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, email, email_verification_expires FROM hosts
            WHERE email_verification_token = ?
        ''', (token,))

    host = cursor.fetchone()

    if not host:
        conn.close()
        flash('Invalid or expired verification link', 'error')
        return redirect(url_for('register'))

    host_dict = dict(host)
    expires = host_dict.get('email_verification_expires')

    # Check if token expired
    if expires:
        expires_dt = datetime.fromisoformat(expires) if isinstance(expires, str) else expires
        if datetime.now() > expires_dt:
            conn.close()
            flash('Verification link has expired. Please register again.', 'error')
            return redirect(url_for('register'))

    # Mark email as verified
    now = datetime.now().isoformat()
    if DB_TYPE == 'postgresql':
        cursor.execute('''
            UPDATE hosts SET email_verified = TRUE, email_verification_token = NULL,
                            email_verification_expires = NULL, updated_at = %s
            WHERE id = %s
        ''', (now, host_dict['id']))
    else:
        cursor.execute('''
            UPDATE hosts SET email_verified = 1, email_verification_token = NULL,
                            email_verification_expires = NULL, updated_at = ?
            WHERE id = ?
        ''', (now, host_dict['id']))

    conn.commit()
    conn.close()

    # Clear session verification data
    session.pop('pending_verification_email', None)
    session.pop('verification_token', None)

    # Log the user in
    session['host_id'] = host_dict['id']
    session['email'] = host_dict['email']
    session['host_name'] = host_dict['email'].split('@')[0]

    flash('Email verified successfully! Complete your account setup.', 'success')
    return redirect(url_for('admin_onboarding'))


@app.route('/resend-verification')
def resend_verification():
    """Resend verification email."""
    # Try to get email from query param first, then session
    email = request.args.get('email') or session.get('pending_verification_email')

    if not email:
        flash('No pending verification found', 'error')
        return redirect(url_for('register'))

    # Verify this email exists and is not yet verified
    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id, email_verified FROM hosts WHERE LOWER(email) = %s', (email.lower(),))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT id, email_verified FROM hosts WHERE LOWER(email) = ?', (email.lower(),))

    host = cursor.fetchone()
    if not host:
        conn.close()
        flash('Email not found. Please register first.', 'error')
        return redirect(url_for('register'))

    host_dict = dict(host)
    email_verified = host_dict.get('email_verified')
    if DB_TYPE == 'sqlite':
        email_verified = bool(email_verified)

    if email_verified:
        conn.close()
        flash('Email already verified. Please login.', 'success')
        return redirect(url_for('admin_login'))

    conn.close()

    # Store in session for the verification page
    session['pending_verification_email'] = email

    # Generate new token
    verification_token = secrets.token_urlsafe(32)
    token_expires = (datetime.now() + timedelta(hours=24)).isoformat()
    now = datetime.now().isoformat()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE hosts SET email_verification_token = %s,
                            email_verification_expires = %s, updated_at = %s
            WHERE LOWER(email) = %s
        ''', (verification_token, token_expires, now, email))
    else:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE hosts SET email_verification_token = ?,
                            email_verification_expires = ?, updated_at = ?
            WHERE LOWER(email) = ?
        ''', (verification_token, token_expires, now, email))

    conn.commit()
    conn.close()

    # Generate verification URL and send email
    verification_url = url_for('verify_email_confirm', token=verification_token, _external=True)
    email_result = send_verification_email(email, verification_url)

    # Update session with new token
    session['verification_token'] = verification_token
    session['email_sent'] = email_result.get('success', False)

    if email_result.get('success'):
        flash('Verification link resent! Check your email.', 'success')
    else:
        flash('Could not send email. Use the link below.', 'error')

    return redirect(url_for('verify_email_pending'))


@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """Admin dashboard - view all reservations for current host."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM reservations
            WHERE host_id = %s
            ORDER BY checkin_date DESC
        ''', (host_id,))
    else:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM reservations
            WHERE host_id = ?
            ORDER BY checkin_date DESC
        ''', (host_id,))

    reservations = cursor.fetchall()
    conn.close()

    # Get base URL for guest links
    base_url = request.host_url.rstrip('/')

    # Get building codes for this host
    building_codes = get_building_codes(host_id)

    return render_template('admin_dashboard.html',
                         reservations=reservations,
                         base_url=base_url,
                         building_codes=building_codes)


@app.route('/admin/onboarding')
@login_required
def admin_onboarding():
    """Onboarding wizard for new hosts."""
    host_id = get_current_host_id()

    # Get current host data
    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM hosts WHERE id = %s', (host_id,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))

    host = cursor.fetchone()
    conn.close()

    host_dict = dict(host) if host else {}

    # If onboarding already completed, redirect to dashboard
    onboarding_completed = host_dict.get('onboarding_completed')
    if DB_TYPE == 'sqlite':
        onboarding_completed = bool(onboarding_completed)

    if onboarding_completed:
        return redirect(url_for('admin_dashboard'))

    return render_template('onboarding.html', host=host_dict)


@app.route('/admin/onboarding', methods=['POST'])
@login_required
def admin_onboarding_save():
    """Save onboarding step data."""
    host_id = get_current_host_id()
    step = request.form.get('step', '1')

    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    if step == '1':
        # Profile step
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        business_type = request.form.get('business_type', 'individual')

        execute_query(cursor, '''
            UPDATE hosts SET name = ?, phone = ?, business_type = ?, updated_at = ?
            WHERE id = ?
        ''', (name, phone, business_type, now, host_id))

    elif step == '2':
        # Business details step
        company_name = request.form.get('company_name', '').strip()
        tax_id = request.form.get('tax_id', '').strip()
        vat_eu = request.form.get('vat_eu', '').strip()
        address_street = request.form.get('address_street', '').strip()
        address_city = request.form.get('address_city', '').strip()
        address_postal = request.form.get('address_postal', '').strip()
        address_country = request.form.get('address_country', 'PL').strip()

        execute_query(cursor, '''
            UPDATE hosts SET company_name = ?, tax_id = ?, vat_eu = ?,
                            address_street = ?, address_city = ?, address_postal = ?,
                            address_country = ?, updated_at = ?
            WHERE id = ?
        ''', (company_name, tax_id, vat_eu, address_street, address_city,
              address_postal, address_country, now, host_id))

    elif step == '3':
        # Invoice settings step
        bank_name = request.form.get('bank_name', '').strip()
        bank_account = request.form.get('bank_account', '').strip()
        payment_days_due = request.form.get('payment_days_due', '0')
        payment_instructions = request.form.get('payment_instructions', '').strip()

        execute_query(cursor, '''
            UPDATE hosts SET bank_name = ?, bank_account = ?,
                            payment_days_due = ?, payment_instructions = ?, updated_at = ?
            WHERE id = ?
        ''', (bank_name, bank_account, int(payment_days_due), payment_instructions, now, host_id))

    elif step == '4':
        # Complete onboarding
        execute_query(cursor, '''
            UPDATE hosts SET onboarding_completed = ?, updated_at = ?
            WHERE id = ?
        ''', (True if DB_TYPE == 'postgresql' else 1, now, host_id))

        conn.commit()
        conn.close()

        flash('Setup complete! Welcome to your dashboard.', 'success')
        return redirect(url_for('admin_dashboard'))

    conn.commit()
    conn.close()

    # Return next step number
    next_step = int(step) + 1
    return jsonify({'success': True, 'next_step': next_step})


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
    if reservation_number is None:
        reservation_number = request.args.get('reservation')

    if not reservation_number:
        return render_template('guest_form.html', error='No reservation number provided')

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE reservation_number = %s', (reservation_number,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE reservation_number = ?', (reservation_number,))

    reservation = cursor.fetchone()

    if not reservation:
        conn.close()
        return render_template('guest_form.html', error=f'Reservation "{reservation_number}" not found')

    reservation = dict(reservation)
    host_id = reservation['host_id']

    # Check if already submitted
    already_submitted = reservation['guest_submitted_at'] is not None

    # Check if can edit (1h before checkout)
    can_edit = can_guest_edit(reservation['checkout_date'])

    # Get building codes for this host
    building_codes = get_building_codes(host_id)

    conn.close()

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
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE reservation_number = %s', (reservation_number,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE reservation_number = ?', (reservation_number,))

    reservation = cursor.fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    reservation = dict(reservation)
    host_id = reservation['host_id']

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
        vat_eu = request.form.get('vat_eu', '').strip() or None

        if not company_name:
            errors.append('Company name is required')
        if not tax_id:
            errors.append('Tax identification number is required')

        first_name = None
        last_name = None

    special_requests = request.form.get('special_requests', '').strip() or None

    if errors:
        conn.close()
        return jsonify({'success': False, 'errors': errors}), 400

    # Update reservation with guest data
    now = datetime.now().isoformat()
    submitted_at = reservation['guest_submitted_at'] or now

    execute_query(cursor, '''
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

    # Fetch updated reservation
    if DB_TYPE == 'postgresql':
        cursor.execute('SELECT * FROM reservations WHERE reservation_number = %s', (reservation_number,))
    else:
        cursor.execute('SELECT * FROM reservations WHERE reservation_number = ?', (reservation_number,))

    updated = dict(cursor.fetchone())
    conn.close()

    # Build display name
    if invoice_type == 'individual':
        display_name = f"{first_name} {last_name}"
    else:
        display_name = company_name

    # Get building codes
    building_codes = get_building_codes(host_id)

    return jsonify({
        'success': True,
        'building_codes': building_codes,
        'apartment_code': updated['apartment_code'],
        'room_number': updated['room_number'],
        'checkin_date': str(updated['checkin_date']),
        'checkout_date': str(updated['checkout_date']),
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
    """API endpoint to get all reservations for current host."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE host_id = %s ORDER BY checkin_date DESC', (host_id,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE host_id = ? ORDER BY checkin_date DESC', (host_id,))

    reservations = cursor.fetchall()
    conn.close()

    return jsonify([dict(r) for r in reservations])


@app.route('/api/reservations/<int:reservation_id>', methods=['PUT'])
@login_required
def update_reservation(reservation_id):
    """Update a reservation (admin only)."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE id = %s AND host_id = %s', (reservation_id, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE id = ? AND host_id = ?', (reservation_id, host_id))

    reservation = cursor.fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    data = request.get_json()
    now = datetime.now().isoformat()

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
    values.append(host_id)

    query = f"UPDATE reservations SET {', '.join(updates)} WHERE id = ? AND host_id = ?"
    execute_query(cursor, query, values)
    conn.commit()

    if DB_TYPE == 'postgresql':
        cursor.execute('SELECT * FROM reservations WHERE id = %s', (reservation_id,))
    else:
        cursor.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,))

    updated = cursor.fetchone()
    conn.close()

    return jsonify({'success': True, 'reservation': dict(updated)})


@app.route('/api/reservations/<int:reservation_id>/reset', methods=['POST'])
@login_required
def reset_reservation(reservation_id):
    """Reset a reservation to pending state (admin testing)."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE id = %s AND host_id = %s', (reservation_id, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE id = ? AND host_id = ?', (reservation_id, host_id))

    reservation = cursor.fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    now = datetime.now().isoformat()

    execute_query(cursor, '''
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
        WHERE id = ? AND host_id = ?
    ''', (now, reservation_id, host_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Reservation reset to pending'})


@app.route('/api/reservations/<int:reservation_id>/generate-invoice', methods=['POST'])
@login_required
def generate_invoice(reservation_id):
    """Generate invoice number and mark as generated (admin only)."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE id = %s AND host_id = %s', (reservation_id, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE id = ? AND host_id = ?', (reservation_id, host_id))

    reservation = cursor.fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    reservation = dict(reservation)

    if not reservation['guest_submitted_at']:
        conn.close()
        return jsonify({'success': False, 'error': 'Guest has not submitted invoice details yet'}), 400

    data = request.get_json() or {}
    now = datetime.now()

    service_name = data.get('service_name', reservation['service_name'] or 'Apartment Rental')
    amount_paid = data.get('amount_paid', reservation['amount_paid'])
    vat_rate = data.get('vat_rate', reservation['vat_rate'] or 8.0)

    if not amount_paid:
        conn.close()
        return jsonify({'success': False, 'error': 'Amount paid is required'}), 400

    # Calculate VAT amount
    vat_amount = round(float(amount_paid) * float(vat_rate) / (100 + float(vat_rate)), 2)

    # Generate invoice number from host's pattern
    invoice_number = generate_invoice_number_from_pattern(host_id)

    execute_query(cursor, '''
        UPDATE reservations SET
            service_name = ?,
            amount_paid = ?,
            vat_rate = ?,
            vat_amount = ?,
            invoice_number = ?,
            invoice_generated_at = ?,
            updated_at = ?
        WHERE id = ? AND host_id = ?
    ''', (service_name, amount_paid, vat_rate, vat_amount, invoice_number,
          now.isoformat(), now.isoformat(), reservation_id, host_id))
    conn.commit()

    if DB_TYPE == 'postgresql':
        cursor.execute('SELECT * FROM reservations WHERE id = %s', (reservation_id,))
    else:
        cursor.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,))

    updated = cursor.fetchone()
    conn.close()

    return jsonify({'success': True, 'reservation': dict(updated)})


@app.route('/api/reservations/export-csv')
@login_required
def export_csv():
    """Export all reservations as CSV for current host."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE host_id = %s ORDER BY checkin_date DESC', (host_id,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE host_id = ? ORDER BY checkin_date DESC', (host_id,))

    reservations = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        'ID', 'Reservation Number', 'Room', 'Apartment Code',
        'Check-in', 'Check-out', 'Invoice Type',
        'First Name', 'Last Name', 'Company Name', 'Tax ID', 'VAT EU',
        'Address', 'Email', 'Special Requests',
        'Service Name', 'Amount Paid', 'VAT Rate', 'VAT Amount',
        'Invoice Number', 'Invoice Generated', 'Guest Submitted', 'Created', 'Updated'
    ]
    writer.writerow(headers)

    for r in reservations:
        r = dict(r)
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
    host_id = get_current_host_id()
    data = request.get_json()
    now = datetime.now().isoformat()

    reservation_number = data.get('reservation_number')
    room_number = data.get('room_number')
    checkin_date = data.get('checkin_date')
    checkout_date = data.get('checkout_date')

    if not all([reservation_number, room_number, checkin_date, checkout_date]):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id FROM reservations WHERE reservation_number = %s AND host_id = %s',
                      (reservation_number, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM reservations WHERE reservation_number = ? AND host_id = ?',
                      (reservation_number, host_id))

    existing = cursor.fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation number already exists'}), 400

    apartment_code = generate_apartment_code()

    execute_query(cursor, '''
        INSERT INTO reservations (
            host_id, reservation_number, room_number, apartment_code,
            checkin_date, checkout_date, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (host_id, reservation_number, room_number, apartment_code, checkin_date, checkout_date, now, now))
    conn.commit()

    # Get the new reservation
    if DB_TYPE == 'postgresql':
        cursor.execute('SELECT * FROM reservations WHERE reservation_number = %s AND host_id = %s',
                      (reservation_number, host_id))
    else:
        cursor.execute('SELECT * FROM reservations WHERE reservation_number = ? AND host_id = ?',
                      (reservation_number, host_id))

    reservation = cursor.fetchone()
    conn.close()

    return jsonify({'success': True, 'reservation': dict(reservation)}), 201


@app.route('/api/reservations/<int:reservation_id>', methods=['DELETE'])
@login_required
def delete_reservation(reservation_id):
    """Delete a reservation (admin only)."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE id = %s AND host_id = %s', (reservation_id, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE id = ? AND host_id = ?', (reservation_id, host_id))

    reservation = cursor.fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    execute_query(cursor, 'DELETE FROM reservations WHERE id = ? AND host_id = ?', (reservation_id, host_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Reservation deleted'})


# ============== BUILDING CODES API ==============

@app.route('/api/building-codes')
@login_required
def api_building_codes():
    """Get all building codes for current host."""
    host_id = get_current_host_id()
    codes = get_building_codes(host_id)
    return jsonify(codes)


@app.route('/api/building-codes', methods=['POST'])
@login_required
def create_building_code():
    """Create a new building code (admin only)."""
    host_id = get_current_host_id()
    data = request.get_json()

    name = data.get('name')
    code = data.get('code')
    display_order = data.get('display_order', 0)

    if not name or not code:
        return jsonify({'success': False, 'error': 'Name and code are required'}), 400

    conn = get_db()
    cursor = conn.cursor()

    execute_query(cursor, '''
        INSERT INTO building_codes (host_id, name, code, display_order)
        VALUES (?, ?, ?, ?)
    ''', (host_id, name, code, display_order))
    conn.commit()

    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM building_codes WHERE host_id = %s ORDER BY id DESC LIMIT 1', (host_id,))
    else:
        cursor.execute('SELECT * FROM building_codes WHERE host_id = ? ORDER BY id DESC LIMIT 1', (host_id,))

    building_code = cursor.fetchone()
    conn.close()

    return jsonify({'success': True, 'building_code': dict(building_code)}), 201


@app.route('/api/building-codes/<int:code_id>', methods=['PUT'])
@login_required
def update_building_code(code_id):
    """Update a building code (admin only)."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM building_codes WHERE id = %s AND host_id = %s', (code_id, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM building_codes WHERE id = ? AND host_id = ?', (code_id, host_id))

    existing = cursor.fetchone()

    if not existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Building code not found'}), 404

    existing = dict(existing)
    data = request.get_json()

    name = data.get('name', existing['name'])
    code = data.get('code', existing['code'])
    display_order = data.get('display_order', existing['display_order'])
    is_active = data.get('is_active', existing['is_active'])

    execute_query(cursor, '''
        UPDATE building_codes SET name = ?, code = ?, display_order = ?, is_active = ?
        WHERE id = ? AND host_id = ?
    ''', (name, code, display_order, is_active, code_id, host_id))
    conn.commit()

    if DB_TYPE == 'postgresql':
        cursor.execute('SELECT * FROM building_codes WHERE id = %s', (code_id,))
    else:
        cursor.execute('SELECT * FROM building_codes WHERE id = ?', (code_id,))

    updated = cursor.fetchone()
    conn.close()

    return jsonify({'success': True, 'building_code': dict(updated)})


@app.route('/api/building-codes/<int:code_id>', methods=['DELETE'])
@login_required
def delete_building_code(code_id):
    """Delete a building code (admin only)."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM building_codes WHERE id = %s AND host_id = %s', (code_id, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM building_codes WHERE id = ? AND host_id = ?', (code_id, host_id))

    existing = cursor.fetchone()

    if not existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Building code not found'}), 404

    execute_query(cursor, 'DELETE FROM building_codes WHERE id = ? AND host_id = ?', (code_id, host_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Building code deleted'})


# ============== INVOICE SETTINGS API ==============

@app.route('/api/invoice-settings')
@login_required
def get_invoice_settings():
    """Get invoice settings for current host."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM hosts WHERE id = %s', (host_id,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))

    host = cursor.fetchone()
    conn.close()

    if host:
        host = dict(host)
        # Return invoice-related fields
        return jsonify({
            'issuer_name': host.get('company_name') or host.get('name'),
            'issuer_address': f"{host.get('address_street', '')}, {host.get('address_postal', '')} {host.get('address_city', '')}".strip(', '),
            'issuer_tax_id': host.get('tax_id'),
            'issuer_vat_eu': host.get('vat_eu'),
            'issuer_bank_name': host.get('bank_name'),
            'issuer_bank_account': host.get('bank_account'),
            'numbering_pattern': host.get('invoice_pattern'),
            'rolling_number_current': host.get('invoice_rolling_number'),
            'payment_days_due': host.get('payment_days_due'),
            'payment_instructions': host.get('payment_instructions')
        })
    return jsonify({})


@app.route('/api/invoice-settings', methods=['PUT'])
@login_required
def update_invoice_settings():
    """Update invoice settings for current host."""
    host_id = get_current_host_id()
    data = request.get_json()
    now = datetime.now().isoformat()

    conn = get_db()
    cursor = conn.cursor()

    # Map old field names to new host table fields
    field_mapping = {
        'issuer_name': 'company_name',
        'issuer_tax_id': 'tax_id',
        'issuer_vat_eu': 'vat_eu',
        'issuer_bank_name': 'bank_name',
        'issuer_bank_account': 'bank_account',
        'numbering_pattern': 'invoice_pattern',
        'rolling_number_current': 'invoice_rolling_number',
        'payment_days_due': 'payment_days_due',
        'payment_instructions': 'payment_instructions'
    }

    updates = []
    values = []

    for old_field, new_field in field_mapping.items():
        if old_field in data:
            updates.append(f'{new_field} = ?')
            values.append(data[old_field])

    # Handle address separately (it's split in the new schema)
    if 'issuer_address' in data:
        # For now, just store in address_street
        updates.append('address_street = ?')
        values.append(data['issuer_address'])

    if updates:
        updates.append('updated_at = ?')
        values.append(now)
        values.append(host_id)

        query = f"UPDATE hosts SET {', '.join(updates)} WHERE id = ?"
        execute_query(cursor, query, values)
        conn.commit()

    conn.close()

    # Return updated settings
    return get_invoice_settings()


def generate_invoice_number_from_pattern(host_id, preview_only=False):
    """Generate the next invoice number based on the host's configured pattern."""
    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM hosts WHERE id = %s', (host_id,))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))

    host = cursor.fetchone()

    if not host:
        conn.close()
        return None

    host = dict(host)
    pattern = json.loads(host.get('invoice_pattern') or '[]')
    rolling_current = host.get('invoice_rolling_number') or 0

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
                execute_query(cursor, 'UPDATE hosts SET invoice_rolling_number = ? WHERE id = ?',
                            (new_rolling, host_id))
                conn.commit()
            parts.append(str(new_rolling).zfill(len(format_spec)))

    conn.close()
    return ''.join(parts)


@app.route('/api/next-invoice-number')
@login_required
def get_next_invoice_number():
    """Get the next invoice number (preview, doesn't increment)."""
    host_id = get_current_host_id()
    invoice_number = generate_invoice_number_from_pattern(host_id, preview_only=True)
    return jsonify({'invoice_number': invoice_number})


def check_invoice_number_unique(host_id, invoice_number, exclude_reservation_id=None):
    """Check if an invoice number is unique for this host."""
    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if exclude_reservation_id:
            cursor.execute(
                'SELECT id FROM reservations WHERE invoice_number = %s AND host_id = %s AND id != %s',
                (invoice_number, host_id, exclude_reservation_id)
            )
        else:
            cursor.execute(
                'SELECT id FROM reservations WHERE invoice_number = %s AND host_id = %s',
                (invoice_number, host_id)
            )
    else:
        cursor = conn.cursor()
        if exclude_reservation_id:
            cursor.execute(
                'SELECT id FROM reservations WHERE invoice_number = ? AND host_id = ? AND id != ?',
                (invoice_number, host_id, exclude_reservation_id)
            )
        else:
            cursor.execute(
                'SELECT id FROM reservations WHERE invoice_number = ? AND host_id = ?',
                (invoice_number, host_id)
            )

    existing = cursor.fetchone()
    conn.close()
    return existing is None


# ============== INVOICE VERSIONS API ==============

@app.route('/api/reservations/<int:reservation_id>/versions')
@login_required
def get_invoice_versions(reservation_id):
    """Get all invoice versions for a reservation."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # First verify reservation belongs to this host
        cursor.execute('SELECT id FROM reservations WHERE id = %s AND host_id = %s', (reservation_id, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM reservations WHERE id = ? AND host_id = ?', (reservation_id, host_id))

    if not cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    if DB_TYPE == 'postgresql':
        cursor.execute('''
            SELECT * FROM invoice_versions
            WHERE reservation_id = %s
            ORDER BY version_number ASC
        ''', (reservation_id,))
    else:
        cursor.execute('''
            SELECT * FROM invoice_versions
            WHERE reservation_id = ?
            ORDER BY version_number ASC
        ''', (reservation_id,))

    versions = cursor.fetchall()
    conn.close()

    return jsonify([dict(v) for v in versions])


@app.route('/api/reservations/<int:reservation_id>/correction', methods=['POST'])
@login_required
def create_invoice_correction(reservation_id):
    """Create an invoice correction."""
    host_id = get_current_host_id()

    conn = get_db()
    if DB_TYPE == 'postgresql':
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM reservations WHERE id = %s AND host_id = %s', (reservation_id, host_id))
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE id = ? AND host_id = ?', (reservation_id, host_id))

    reservation = cursor.fetchone()

    if not reservation:
        conn.close()
        return jsonify({'success': False, 'error': 'Reservation not found'}), 404

    reservation = dict(reservation)

    if not reservation['invoice_number']:
        conn.close()
        return jsonify({'success': False, 'error': 'No invoice to correct'}), 400

    data = request.get_json() or {}
    now = datetime.now().isoformat()

    # Get current version count
    if DB_TYPE == 'postgresql':
        cursor.execute('SELECT COUNT(*) as count FROM invoice_versions WHERE reservation_id = %s', (reservation_id,))
    else:
        cursor.execute('SELECT COUNT(*) FROM invoice_versions WHERE reservation_id = ?', (reservation_id,))

    result = cursor.fetchone()
    version_count = result['count'] if isinstance(result, dict) else result[0]

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
            'amount_paid': float(reservation['amount_paid']) if reservation['amount_paid'] else None,
            'vat_rate': float(reservation['vat_rate']) if reservation['vat_rate'] else None,
            'vat_amount': float(reservation['vat_amount']) if reservation['vat_amount'] else None,
            'invoice_generated_at': reservation['invoice_generated_at']
        }
        execute_query(cursor, '''
            INSERT INTO invoice_versions (reservation_id, version_number, invoice_number, invoice_data, created_at)
            VALUES (?, 1, ?, ?, ?)
        ''', (reservation_id, reservation['invoice_number'], json.dumps(original_data), now))
        version_count = 1

    new_version = version_count + 1

    # Generate correction invoice number
    base_number = reservation['invoice_number'].split('_CORRECTED')[0]
    if new_version == 2:
        new_invoice_number = f"{base_number}_CORRECTED"
    else:
        new_invoice_number = f"{base_number}_CORRECTED_{new_version - 1}"

    # Check uniqueness
    if not check_invoice_number_unique(host_id, new_invoice_number, reservation_id):
        conn.close()
        return jsonify({'success': False, 'error': 'Invoice number already exists'}), 400

    service_name = data.get('service_name', reservation['service_name'])
    amount_paid = data.get('amount_paid', reservation['amount_paid'])
    vat_rate = data.get('vat_rate', reservation['vat_rate'])

    vat_amount = round(float(amount_paid) * float(vat_rate) / (100 + float(vat_rate)), 2) if amount_paid else 0

    correction_data = {
        'invoice_type': data.get('invoice_type', reservation['invoice_type']),
        'first_name': data.get('first_name', reservation['first_name']),
        'last_name': data.get('last_name', reservation['last_name']),
        'company_name': data.get('company_name', reservation['company_name']),
        'tax_id': data.get('tax_id', reservation['tax_id']),
        'vat_eu': data.get('vat_eu', reservation['vat_eu']),
        'address': data.get('address', reservation['address']),
        'service_name': service_name,
        'amount_paid': float(amount_paid) if amount_paid else None,
        'vat_rate': float(vat_rate) if vat_rate else None,
        'vat_amount': vat_amount,
        'invoice_generated_at': now
    }

    execute_query(cursor, '''
        INSERT INTO invoice_versions (reservation_id, version_number, invoice_number, invoice_data, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (reservation_id, new_version, new_invoice_number, json.dumps(correction_data), now))

    execute_query(cursor, '''
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
        WHERE id = ? AND host_id = ?
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
        reservation_id,
        host_id
    ))
    conn.commit()

    if DB_TYPE == 'postgresql':
        cursor.execute('SELECT * FROM reservations WHERE id = %s', (reservation_id,))
    else:
        cursor.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,))

    updated = cursor.fetchone()
    conn.close()

    return jsonify({'success': True, 'reservation': dict(updated), 'version': new_version})


# ============== MAIN ==============

if __name__ == '__main__':
    import sys

    # Check for reset flag
    if len(sys.argv) > 1 and sys.argv[1] == '--reset':
        from database import reset_db
        reset_db()
    else:
        init_db()
        seed_demo_data()

    print("\n" + "="*60)
    print("Guest Check-in & Invoice Collection System")
    print("="*60)
    print(f"\nDatabase: {DB_TYPE}")
    print("\nAdmin Dashboard: http://localhost:5000/admin")
    print("Demo Guest Links:")
    print("  - Pending: http://localhost:5000/guest?reservation=DEMO-001")
    print("  - Submitted: http://localhost:5000/guest?reservation=DEMO-002")
    print("  - With Invoice: http://localhost:5000/guest?reservation=DEMO-003")
    print("  - Old (14+ days): http://localhost:5000/guest?reservation=DEMO-004")
    print("\nDemo Host Credentials:")
    print(f"  Email: {DEMO_EMAIL}")
    print(f"  Password: {DEMO_PASSWORD}")
    print("="*60 + "\n")

    app.run(debug=True, port=5000)
