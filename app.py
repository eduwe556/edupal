from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta
import os
import requests
import json
import base64
import hmac
import hashlib
from functools import wraps
import uuid

app = Flask(__name__)

# Use environment variables for production, with fallback for local dev
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

DATABASE = 'edupal.db'
DEVELOPER_EMAIL = os.environ.get('DEVELOPER_EMAIL', 'taliatibrahim457@gmail.com')

# Monnify Credentials (use environment variables in production)
MONNIFY_API_KEY = os.environ.get('MONNIFY_API_KEY', 'MK_TEST_XB68SA8MXA')
MONNIFY_SECRET_KEY = os.environ.get('MONNIFY_SECRET_KEY', 'JJ4PXL7JVWN8ZSZDBCMY4JG8BQN4BKVD')
MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
MONNIFY_CONTRACT_CODE = os.environ.get('MONNIFY_CONTRACT_CODE', '1153231557')

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_name TEXT NOT NULL,
            admin_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            plan TEXT DEFAULT 'trial',
            subscription_start TEXT,
            subscription_end TEXT,
            student_add_count INTEGER DEFAULT 0,
            monnify_reference TEXT,
            role TEXT DEFAULT 'user'
        );

        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            parent_phone TEXT,
            parent_email TEXT,
            address TEXT,
            class_id INTEGER,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS fee_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            payment_date TEXT DEFAULT CURRENT_DATE,
            note TEXT,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT DEFAULT CURRENT_DATE,
            status TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            ca_score REAL,
            exam_score REAL,
            total REAL,
            grade TEXT,
            term TEXT,
            session TEXT,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS class_fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(class_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reference TEXT UNIQUE NOT NULL,
            plan TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            account_number TEXT,
            account_bank TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

init_db()

# Helper functions
def get_subscription(user_id):
    conn = get_db()
    user = conn.execute('SELECT plan, subscription_start, subscription_end, student_add_count FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user

def is_subscribed(user_id):
    sub = get_subscription(user_id)
    if not sub:
        return False
    if sub['plan'] == 'premium':
        return True
    if sub['subscription_end']:
        today = date.today().isoformat()
        return today <= sub['subscription_end']
    return False

def subscription_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not is_subscribed(session['user_id']):
            flash('Please subscribe to access this feature.', 'warning')
            return redirect(url_for('subscribe'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def calculate_grade(total):
    if total >= 70:
        return 'A'
    elif total >= 60:
        return 'B'
    elif total >= 50:
        return 'C'
    elif total >= 45:
        return 'D'
    elif total >= 40:
        return 'E'
    else:
        return 'F'

# ----------------- Monnify API Helpers -----------------
def monnify_auth():
    """Get access token from Monnify."""
    url = f"{MONNIFY_BASE_URL}/api/v1/auth/login"
    auth_string = base64.b64encode(f"{MONNIFY_API_KEY}:{MONNIFY_SECRET_KEY}".encode()).decode()
    headers = {
        'Authorization': f'Basic {auth_string}',
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data['requestSuccessful']:
                return data['responseBody']['accessToken']
            else:
                print("Auth error:", data['responseMessage'])
                return None
        else:
            print("Auth HTTP error:", response.status_code, response.text)
            return None
    except Exception as e:
        print("Auth exception:", str(e))
        return None

def get_existing_virtual_account(monnify_ref):
    """Fetch an existing reserved account using its reference."""
    token = monnify_auth()
    if not token:
        raise Exception("Could not authenticate with Monnify")
    url = f"{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{monnify_ref}"
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(url, headers=headers)
    print("GET reserved account response:", response.text)
    if response.status_code == 200:
        data = response.json()
        if data['requestSuccessful']:
            body = data['responseBody']
            if body.get('accountNumber') and body.get('bankName'):
                return body
            accounts = body.get('accounts')
            if accounts and isinstance(accounts, list) and len(accounts) > 0:
                first_account = accounts[0]
                if first_account.get('accountNumber') and first_account.get('bankName'):
                    return {
                        'accountNumber': first_account['accountNumber'],
                        'bankName': first_account['bankName'],
                        'accountName': body.get('accountName'),
                        'accounts': accounts
                    }
    return None

def create_virtual_account(email, amount, reference, plan_name):
    """Create a reserved account or fetch existing one."""
    conn = get_db()
    user = conn.execute('SELECT monnify_reference FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()

    if user and user['monnify_reference']:
        existing = get_existing_virtual_account(user['monnify_reference'])
        if existing and existing.get('accountNumber') and existing.get('bankName'):
            return existing

    token = monnify_auth()
    if not token:
        raise Exception("Could not authenticate with Monnify")

    if not email:
        conn = get_db()
        user = conn.execute('SELECT email FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        if user:
            email = user['email']
        else:
            raise Exception("User email not found")

    url = f"{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    data = {
        "accountReference": reference,
        "accountName": f"EduPal {plan_name}",
        "currencyCode": "NGN",
        "contractCode": MONNIFY_CONTRACT_CODE,
        "customerEmail": email,
        "customerName": session.get('admin_name', 'User'),
        "incomeSplitConfig": [],
        "restrictPaymentSource": False,
        "getAllAvailableBanks": True,
        "amount": amount
    }
    response = requests.post(url, headers=headers, json=data)
    print("Monnify raw response:", response.text)
    if response.status_code == 200:
        resp_data = response.json()
        if resp_data['requestSuccessful']:
            body = resp_data['responseBody']
            account_number = body.get('accountNumber')
            bank_name = body.get('bankName')
            if account_number and bank_name:
                conn = get_db()
                conn.execute('UPDATE users SET monnify_reference = ? WHERE id = ?', (reference, session['user_id']))
                conn.commit()
                conn.close()
                return body
            accounts = body.get('accounts')
            if accounts and isinstance(accounts, list) and len(accounts) > 0:
                first_account = accounts[0]
                account_number = first_account.get('accountNumber')
                bank_name = first_account.get('bankName')
                if account_number and bank_name:
                    conn = get_db()
                    conn.execute('UPDATE users SET monnify_reference = ? WHERE id = ?', (reference, session['user_id']))
                    conn.commit()
                    conn.close()
                    return {
                        'accountNumber': account_number,
                        'bankName': bank_name,
                        'accountName': body.get('accountName'),
                        'accounts': accounts
                    }
            print("Parsed body:", body)
            raise Exception("Could not extract account details from Monnify response")
        else:
            raise Exception(f"Monnify error: {resp_data['responseMessage']}")
    else:
        raise Exception(f"HTTP error {response.status_code}: {response.text}")

def verify_transaction(reference):
    """Check if a transaction with given reference has been paid."""
    token = monnify_auth()
    if not token:
        return False
    url = f"{MONNIFY_BASE_URL}/api/v1/transactions/search"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    data = {
        "paymentReference": reference,
        "page": 0,
        "size": 10
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        print("Verify response:", response.text)
        if response.status_code == 200:
            resp = response.json()
            if resp['requestSuccessful']:
                transactions = resp['responseBody']['content']
                for tx in transactions:
                    if tx.get('paymentStatus') == 'PAID':
                        return True
        else:
            print("Verify HTTP error:", response.status_code, response.text)
    except Exception as e:
        print("Verify exception:", str(e))
    return False

def activate_subscription(user_id, plan):
    today = date.today()
    if plan == 'basic':
        end_date = today + timedelta(days=90)
    elif plan == 'silver':
        end_date = today + timedelta(days=180)
    elif plan == 'gold':
        end_date = today + timedelta(days=270)
    else:
        return
    conn = get_db()
    conn.execute('UPDATE users SET plan = ?, subscription_start = ?, subscription_end = ? WHERE id = ?',
                 (plan, today.isoformat(), end_date.isoformat(), user_id))
    conn.commit()
    conn.close()

# ----------------- Auth Routes -----------------
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    elif 'teacher_id' in session:
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        school_name = request.form['school_name'].strip()
        admin_name = request.form['admin_name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if not school_name or not admin_name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        conn = get_db()
        existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('An account with this email already exists. Please log in.', 'danger')
            conn.close()
            return redirect(url_for('register'))

        password_hash = generate_password_hash(password)
        if email == DEVELOPER_EMAIL:
            plan = 'premium'
            sub_start = date.today().isoformat()
            sub_end = '2099-12-31'
            student_add_count = 0
            role = 'admin'
        else:
            plan = 'trial'
            sub_start = None
            sub_end = None
            student_add_count = 0
            role = 'user'

        conn.execute(
            'INSERT INTO users (school_name, admin_name, email, password_hash, plan, subscription_start, subscription_end, student_add_count, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (school_name, admin_name, email, password_hash, plan, sub_start, sub_end, student_add_count, role)
        )
        conn.commit()
        conn.close()

        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['school_name'] = user['school_name']
            session['admin_name'] = user['admin_name']
            session['email'] = user['email']
            session['role'] = user['role']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    class_count = conn.execute('SELECT COUNT(*) FROM classes WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    fee_total = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM fee_payments WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    sub = get_subscription(session['user_id'])
    conn.close()
    today = date.today().isoformat()
    return render_template('dashboard.html', student_count=student_count, class_count=class_count, fee_total=fee_total, subscription=sub, today=today)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ----------------- Subscription Routes -----------------
@app.route('/subscribe', methods=['GET', 'POST'])
def subscribe():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Fetch current prices from settings
    conn = get_db()
    basic_price_row = conn.execute('SELECT value FROM settings WHERE key="basic_price"').fetchone()
    silver_price_row = conn.execute('SELECT value FROM settings WHERE key="silver_price"').fetchone()
    gold_price_row = conn.execute('SELECT value FROM settings WHERE key="gold_price"').fetchone()
    conn.close()

    basic_price = float(basic_price_row['value']) if basic_price_row else 30000
    silver_price = float(silver_price_row['value']) if silver_price_row else 50000
    gold_price = float(gold_price_row['value']) if gold_price_row else 70000

    if request.method == 'POST':
        plan = request.form.get('plan')
        if plan not in ['basic', 'silver', 'gold']:
            flash('Invalid plan.', 'danger')
            return redirect(url_for('subscribe'))

        amounts = {
            'basic': basic_price,
            'silver': silver_price,
            'gold': gold_price,
        }
        amount = amounts[plan]
        plan_name = {'basic': 'Basic Plan (1 Term)', 'silver': 'Silver Plan (2 Terms)', 'gold': 'Gold Plan (3 Terms)'}[plan]

        reference = f'edupal_{session["user_id"]}_{uuid.uuid4().hex[:10]}'

        try:
            account_info = create_virtual_account(session.get('email'), amount, reference, plan_name)
            account_number = account_info.get('accountNumber')
            bank_name = account_info.get('bankName')
            if not account_number or not bank_name:
                raise Exception("Missing account details in Monnify response")
            conn = get_db()
            conn.execute('''
                INSERT INTO subscriptions (user_id, reference, plan, amount, status, account_number, account_bank)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
            ''', (session['user_id'], reference, plan, amount, account_number, bank_name))
            conn.commit()
            conn.close()
            return redirect(url_for('payment_waiting', reference=reference))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(url_for('subscribe'))

    return render_template(
        'subscribe.html',
        basic_price=basic_price,
        silver_price=silver_price,
        gold_price=gold_price
    )

@app.route('/payment/waiting/<reference>')
def payment_waiting(reference):
    conn = get_db()
    sub = conn.execute('SELECT * FROM subscriptions WHERE reference = ?', (reference,)).fetchone()
    conn.close()
    if not sub:
        flash('Subscription not found.', 'danger')
        return redirect(url_for('subscribe'))
    return render_template('payment_waiting.html', sub=sub)

@app.route('/payment/confirm/<reference>')
def payment_confirm(reference):
    if verify_transaction(reference):
        conn = get_db()
        sub = conn.execute('SELECT * FROM subscriptions WHERE reference = ?', (reference,)).fetchone()
        if sub and sub['status'] == 'pending':
            activate_subscription(sub['user_id'], sub['plan'])
            conn.execute('UPDATE subscriptions SET status = "confirmed" WHERE id = ?', (sub['id'],))
            conn.commit()
            conn.close()
            flash('Payment confirmed! Subscription activated.', 'success')
            return redirect(url_for('dashboard'))
        else:
            conn.close()
            flash('Subscription already activated or invalid.', 'info')
            return redirect(url_for('dashboard'))
    else:
        flash('Payment not yet received. Please wait a few minutes or check your transfer.', 'danger')
        return redirect(url_for('payment_waiting', reference=reference))

# ----------------- Student Routes -----------------
@app.route('/students')
@subscription_required
def students():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    students_raw = conn.execute('''
        SELECT students.*, classes.name as class_name 
        FROM students 
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE students.user_id = ?
        ORDER BY students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()

    class_fees = {row['class_id']: row['amount'] for row in conn.execute(
        'SELECT class_id, amount FROM class_fees WHERE user_id = ?', (session['user_id'],)
    ).fetchall()}

    payments = {row['student_id']: row['total_paid'] for row in conn.execute(
        'SELECT student_id, SUM(amount) as total_paid FROM fee_payments WHERE user_id = ? GROUP BY student_id',
        (session['user_id'],)
    ).fetchall()}

    student_data = []
    for s in students_raw:
        student = dict(s)
        class_id = student['class_id']
        fee = class_fees.get(class_id, 0)
        paid = payments.get(student['id'], 0)
        balance = fee - paid
        student['fee'] = fee
        student['paid'] = paid
        student['balance'] = balance
        student_data.append(student)

    conn.close()
    return render_template('students.html', students=student_data)

@app.route('/students/add', methods=['GET', 'POST'])
def add_student():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    user_sub = get_subscription(session['user_id'])
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        if user_sub['plan'] == 'trial' and user_sub['student_add_count'] >= 1:
            flash('Trial allows only one student. Please subscribe to add more.', 'danger')
            return redirect(url_for('subscribe'))
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        address = request.form.get('address', '').strip()
        class_id = request.form.get('class_id') or None

        if not first_name or not last_name:
            flash('First name and last name are required.', 'danger')
        else:
            conn.execute(
                'INSERT INTO students (first_name, last_name, parent_phone, parent_email, address, class_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (first_name, last_name, parent_phone, parent_email, address, class_id, session['user_id'])
            )
            if user_sub['plan'] == 'trial':
                conn.execute('UPDATE users SET student_add_count = student_add_count + 1 WHERE id = ?', (session['user_id'],))
            conn.commit()
            flash('Student added successfully!', 'success')
            return redirect(url_for('students'))
    conn.close()
    return render_template('add_student.html', classes=classes)

@app.route('/students/edit/<int:student_id>', methods=['GET', 'POST'])
@subscription_required
def edit_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student = conn.execute(
        'SELECT * FROM students WHERE id = ? AND user_id = ?',
        (student_id, session['user_id'])
    ).fetchone()
    if not student:
        flash('Student not found.', 'danger')
        conn.close()
        return redirect(url_for('students'))

    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        address = request.form.get('address', '').strip()
        class_id = request.form.get('class_id') or None

        if not first_name or not last_name:
            flash('First name and last name are required.', 'danger')
        else:
            conn.execute(
                'UPDATE students SET first_name = ?, last_name = ?, parent_phone = ?, parent_email = ?, address = ?, class_id = ? WHERE id = ? AND user_id = ?',
                (first_name, last_name, parent_phone, parent_email, address, class_id, student_id, session['user_id'])
            )
            conn.commit()
            flash('Student updated successfully!', 'success')
            conn.close()
            return redirect(url_for('students'))
    conn.close()
    return render_template('edit_student.html', student=student, classes=classes)

@app.route('/students/delete/<int:student_id>')
@subscription_required
def delete_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student = conn.execute(
        'SELECT id FROM students WHERE id = ? AND user_id = ?',
        (student_id, session['user_id'])
    ).fetchone()
    if student:
        conn.execute('DELETE FROM fee_payments WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM attendance WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM results WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM students WHERE id = ?', (student_id,))
        conn.commit()
        flash('Student deleted.', 'success')
    else:
        flash('Student not found.', 'danger')
    conn.close()
    return redirect(url_for('students'))

# ----------------- Class Routes -----------------
@app.route('/classes')
@subscription_required
def classes():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    class_list = conn.execute('''
        SELECT classes.*, COUNT(students.id) as student_count
        FROM classes
        LEFT JOIN students ON students.class_id = classes.id
        WHERE classes.user_id = ?
        GROUP BY classes.id
        ORDER BY classes.name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('classes.html', classes=class_list)

@app.route('/classes/add', methods=['GET', 'POST'])
@subscription_required
def add_class():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Class name is required.', 'danger')
            return redirect(url_for('add_class'))
        conn = get_db()
        conn.execute('INSERT INTO classes (name, user_id) VALUES (?, ?)', (name, session['user_id']))
        conn.commit()
        conn.close()
        flash('Class added successfully!', 'success')
        return redirect(url_for('classes'))
    return render_template('add_class.html')

@app.route('/classes/delete/<int:class_id>')
@subscription_required
def delete_class(class_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE class_id = ?', (class_id,)).fetchone()[0]
    if student_count > 0:
        flash('Cannot delete class with students. Reassign students first.', 'danger')
    else:
        conn.execute('DELETE FROM class_fees WHERE class_id = ?', (class_id,))
        conn.execute('DELETE FROM teachers WHERE class_id = ?', (class_id,))
        conn.execute('DELETE FROM classes WHERE id = ? AND user_id = ?', (class_id, session['user_id']))
        conn.commit()
        flash('Class deleted.', 'success')
    conn.close()
    return redirect(url_for('classes'))

# ----------------- Fee Routes -----------------
@app.route('/fees')
@subscription_required
def fees():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    payments = conn.execute('''
        SELECT fee_payments.*, students.first_name, students.last_name, classes.name as class_name
        FROM fee_payments
        JOIN students ON fee_payments.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE fee_payments.user_id = ?
        ORDER BY fee_payments.payment_date DESC, fee_payments.id DESC
    ''', (session['user_id'],)).fetchall()
    total_collected = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM fee_payments WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    conn.close()
    return render_template('fees.html', payments=payments, total_collected=total_collected)

@app.route('/fees/add', methods=['GET', 'POST'])
@subscription_required
def add_fee():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    students = conn.execute('''
        SELECT students.id, students.first_name, students.last_name, classes.name as class_name
        FROM students
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE students.user_id = ?
        ORDER BY students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        student_id = request.form['student_id']
        amount = request.form['amount']
        note = request.form.get('note', '').strip()
        payment_date = request.form.get('payment_date')

        if not student_id or not amount:
            flash('Student and amount are required.', 'danger')
        else:
            try:
                amount = float(amount)
                if amount <= 0:
                    flash('Amount must be greater than zero.', 'danger')
                else:
                    if payment_date:
                        conn.execute('INSERT INTO fee_payments (amount, payment_date, note, student_id, user_id) VALUES (?, ?, ?, ?, ?)', (amount, payment_date, note, student_id, session['user_id']))
                    else:
                        conn.execute('INSERT INTO fee_payments (amount, note, student_id, user_id) VALUES (?, ?, ?, ?)', (amount, note, student_id, session['user_id']))
                    conn.commit()
                    flash('Fee payment recorded successfully!', 'success')
                    conn.close()
                    return redirect(url_for('fees'))
            except ValueError:
                flash('Invalid amount format.', 'danger')

    today = date.today().isoformat()
    conn.close()
    return render_template('add_fee.html', students=students, current_date=today)

@app.route('/fees/structure', methods=['GET', 'POST'])
@subscription_required
def fee_structure():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    if request.method == 'POST':
        for key, value in request.form.items():
            if key.startswith('fee_'):
                class_id = key[4:]
                amount = value.strip()
                if amount:
                    try:
                        amt = float(amount)
                        existing = conn.execute('SELECT id FROM class_fees WHERE class_id = ? AND user_id = ?', (class_id, session['user_id'])).fetchone()
                        if existing:
                            conn.execute('UPDATE class_fees SET amount = ? WHERE id = ?', (amt, existing['id']))
                        else:
                            conn.execute('INSERT INTO class_fees (class_id, amount, user_id) VALUES (?, ?, ?)', (class_id, amt, session['user_id']))
                    except ValueError:
                        flash('Invalid amount for class ID: ' + class_id, 'danger')
        conn.commit()
        conn.close()
        flash('Fee structure updated successfully!', 'success')
        return redirect(url_for('fee_structure'))

    classes = conn.execute('SELECT * FROM classes WHERE user_id = ? ORDER BY name', (session['user_id'],)).fetchall()
    class_fees = {row['class_id']: row['amount'] for row in conn.execute('SELECT class_id, amount FROM class_fees WHERE user_id = ?', (session['user_id'],)).fetchall()}
    conn.close()
    return render_template('fee_structure.html', classes=classes, class_fees=class_fees)

# ----------------- Attendance Routes (Admin) -----------------
@app.route('/attendance')
@subscription_required
def attendance():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    records = conn.execute('''
        SELECT attendance.*, students.first_name, students.last_name, classes.name as class_name
        FROM attendance
        JOIN students ON attendance.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE attendance.user_id = ?
        ORDER BY attendance.date DESC, students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('attendance.html', records=records)

@app.route('/attendance/mark', methods=['GET', 'POST'])
@subscription_required
def mark_attendance():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        class_id = request.form.get('class_id')
        attendance_date = request.form.get('attendance_date')
        if not class_id or not attendance_date:
            flash('Please select class and date.', 'danger')
            return redirect(url_for('mark_attendance'))

        students = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (class_id, session['user_id'])).fetchall()

        for student in students:
            status_key = f'status_{student["id"]}'
            status = request.form.get(status_key)
            if status:
                existing = conn.execute('SELECT id FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], attendance_date, session['user_id'])).fetchone()
                if existing:
                    conn.execute('UPDATE attendance SET status = ? WHERE id = ?', (status, existing['id']))
                else:
                    conn.execute('INSERT INTO attendance (date, status, student_id, user_id) VALUES (?, ?, ?, ?)', (attendance_date, status, student['id'], session['user_id']))
        conn.commit()
        conn.close()
        flash('Attendance saved successfully!', 'success')
        return redirect(url_for('attendance'))

    today = date.today().isoformat()
    selected_class = request.args.get('class_id')
    selected_date = request.args.get('date', today)
    students = []
    if selected_class:
        student_rows = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (selected_class, session['user_id'])).fetchall()
        for row in student_rows:
            student = dict(row)
            att = conn.execute('SELECT status FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], selected_date, session['user_id'])).fetchone()
            student['existing_status'] = att['status'] if att else None
            students.append(student)
    conn.close()
    return render_template('mark_attendance.html', classes=classes, students=students, selected_class=selected_class, selected_date=selected_date, today=today)

# ----------------- Teacher Management (Admin) -----------------
@app.route('/teachers')
@subscription_required
def teachers():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    teachers = conn.execute('''
        SELECT teachers.*, classes.name as class_name
        FROM teachers
        JOIN classes ON teachers.class_id = classes.id
        WHERE teachers.user_id = ?
        ORDER BY teachers.name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('teachers.html', teachers=teachers)

@app.route('/teachers/add', methods=['GET', 'POST'])
@subscription_required
def add_teacher():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        class_id = request.form['class_id']

        if not name or not email or not password or not class_id:
            flash('All fields are required.', 'danger')
            return redirect(url_for('add_teacher'))

        existing = conn.execute('SELECT id FROM teachers WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('A teacher with this email already exists.', 'danger')
            conn.close()
            return redirect(url_for('add_teacher'))

        password_hash = generate_password_hash(password)
        conn.execute(
            'INSERT INTO teachers (name, email, password_hash, class_id, user_id) VALUES (?, ?, ?, ?, ?)',
            (name, email, password_hash, class_id, session['user_id'])
        )
        conn.commit()
        conn.close()
        flash('Teacher account created successfully!', 'success')
        return redirect(url_for('teachers'))

    conn.close()
    return render_template('add_teacher.html', classes=classes)

@app.route('/teachers/delete/<int:teacher_id>')
@subscription_required
def delete_teacher(teacher_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    conn.execute('DELETE FROM teachers WHERE id = ? AND user_id = ?', (teacher_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('Teacher deleted.', 'success')
    return redirect(url_for('teachers'))

# ----------------- Teacher Auth & Attendance -----------------
@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db()
        teacher = conn.execute('SELECT * FROM teachers WHERE email = ?', (email,)).fetchone()
        conn.close()

        if teacher and check_password_hash(teacher['password_hash'], password):
            session['teacher_id'] = teacher['id']
            session['teacher_name'] = teacher['name']
            session['teacher_class_id'] = teacher['class_id']
            session['user_id'] = teacher['user_id']
            flash('Teacher login successful!', 'success')
            return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid teacher credentials.', 'danger')

    return render_template('teacher_login.html')

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if 'teacher_id' not in session:
        return redirect(url_for('teacher_login'))
    conn = get_db()
    class_info = conn.execute('SELECT name FROM classes WHERE id = ?', (session['teacher_class_id'],)).fetchone()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE class_id = ? AND user_id = ?', (session['teacher_class_id'], session['user_id'])).fetchone()[0]
    conn.close()
    return render_template('teacher_dashboard.html', class_name=class_info['name'] if class_info else 'Unknown', student_count=student_count)

@app.route('/teacher/attendance', methods=['GET', 'POST'])
def teacher_attendance():
    if 'teacher_id' not in session:
        return redirect(url_for('teacher_login'))

    conn = get_db()
    class_id = session['teacher_class_id']
    user_id = session['user_id']

    if request.method == 'POST':
        attendance_date = request.form.get('attendance_date')
        if not attendance_date:
            flash('Please select a date.', 'danger')
            return redirect(url_for('teacher_attendance'))

        students = conn.execute('SELECT id FROM students WHERE class_id = ? AND user_id = ?', (class_id, user_id)).fetchall()
        for student in students:
            status_key = f'status_{student["id"]}'
            status = request.form.get(status_key)
            if status:
                existing = conn.execute('SELECT id FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], attendance_date, user_id)).fetchone()
                if existing:
                    conn.execute('UPDATE attendance SET status = ? WHERE id = ?', (status, existing['id']))
                else:
                    conn.execute('INSERT INTO attendance (date, status, student_id, user_id) VALUES (?, ?, ?, ?)', (attendance_date, status, student['id'], user_id))
        conn.commit()
        conn.close()
        flash('Attendance saved successfully!', 'success')
        return redirect(url_for('teacher_dashboard'))

    today = date.today().isoformat()
    selected_date = request.args.get('date', today)
    students = []
    student_rows = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (class_id, user_id)).fetchall()
    for row in student_rows:
        student = dict(row)
        att = conn.execute('SELECT status FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], selected_date, user_id)).fetchone()
        student['existing_status'] = att['status'] if att else None
        students.append(student)

    class_name = conn.execute('SELECT name FROM classes WHERE id = ?', (class_id,)).fetchone()['name']
    conn.close()
    return render_template('teacher_attendance.html', students=students, class_name=class_name, selected_date=selected_date, today=today)

@app.route('/teacher/logout')
def teacher_logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('teacher_login'))

# ----------------- Results Routes (Admin only) -----------------
@app.route('/results')
@subscription_required
def results():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    class_id = request.args.get('class_id')
    term = request.args.get('term')
    session_year = request.args.get('session')

    query = '''
        SELECT results.*, students.first_name, students.last_name, classes.name as class_name
        FROM results
        JOIN students ON results.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE results.user_id = ?
    '''
    params = [session['user_id']]
    if class_id:
        query += ' AND students.class_id = ?'
        params.append(class_id)
    if term:
        query += ' AND results.term = ?'
        params.append(term)
    if session_year:
        query += ' AND results.session = ?'
        params.append(session_year)
    query += ' ORDER BY results.session DESC, results.term DESC, students.last_name, students.first_name, results.subject'

    records = conn.execute(query, params).fetchall()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('results.html', records=records, classes=classes, selected_class=class_id, selected_term=term, selected_session=session_year)

@app.route('/results/add', methods=['GET', 'POST'])
@subscription_required
def add_result():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        class_id = request.form.get('class_id')
        subject = request.form.get('subject').strip()
        term = request.form.get('term').strip()
        session_year = request.form.get('session').strip()

        if not class_id or not subject or not term or not session_year:
            flash('All fields are required.', 'danger')
            return redirect(url_for('add_result'))

        students = conn.execute('SELECT id FROM students WHERE class_id = ? AND user_id = ?', (class_id, session['user_id'])).fetchall()
        for student in students:
            ca_key = f'ca_{student["id"]}'
            exam_key = f'exam_{student["id"]}'
            ca_score = request.form.get(ca_key, 0) or 0
            exam_score = request.form.get(exam_key, 0) or 0
            try:
                ca = float(ca_score)
                exam = float(exam_score)
            except ValueError:
                flash('Invalid score values.', 'danger')
                conn.close()
                return redirect(url_for('add_result'))
            total = ca + exam
            grade = calculate_grade(total)
            existing = conn.execute('''SELECT id FROM results WHERE student_id = ? AND subject = ? AND term = ? AND session = ? AND user_id = ?''', (student['id'], subject, term, session_year, session['user_id'])).fetchone()
            if existing:
                conn.execute('UPDATE results SET ca_score = ?, exam_score = ?, total = ?, grade = ? WHERE id = ?', (ca, exam, total, grade, existing['id']))
            else:
                conn.execute('INSERT INTO results (subject, ca_score, exam_score, total, grade, term, session, student_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (subject, ca, exam, total, grade, term, session_year, student['id'], session['user_id']))
        conn.commit()
        conn.close()
        flash('Results saved successfully!', 'success')
        return redirect(url_for('results'))

    selected_class = request.args.get('class_id')
    students = []
    if selected_class:
        students = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (selected_class, session['user_id'])).fetchall()
    conn.close()
    today = date.today().isoformat()
    return render_template('add_result.html', classes=classes, selected_class=selected_class, students=students, today=today)

# ----------------- Admin Panel Routes -----------------
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    total_users = conn.execute('SELECT COUNT(*) FROM users WHERE role != "admin"').fetchone()[0]
    subscribed_users = conn.execute('SELECT COUNT(*) FROM users WHERE role != "admin" AND plan != "trial"').fetchone()[0]
    trial_users = total_users - subscribed_users
    conn.close()
    return render_template('admin_dashboard.html', total_users=total_users, subscribed_users=subscribed_users, trial_users=trial_users)

@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users WHERE role != "admin" ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)

@app.route('/admin/announcements')
@admin_required
def admin_announcements():
    conn = get_db()
    announcements = conn.execute('SELECT * FROM announcements ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin_announcements.html', announcements=announcements)

@app.route('/admin/announcements/add', methods=['GET', 'POST'])
@admin_required
def admin_add_announcement():
    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin_add_announcement'))
        conn = get_db()
        conn.execute('INSERT INTO announcements (title, content) VALUES (?, ?)', (title, content))
        conn.commit()
        conn.close()
        flash('Announcement posted successfully!', 'success')
        return redirect(url_for('admin_announcements'))
    return render_template('admin_add_announcement.html')

@app.route('/admin/announcements/edit/<int:ann_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_announcement(ann_id):
    conn = get_db()
    announcement = conn.execute('SELECT * FROM announcements WHERE id = ?', (ann_id,)).fetchone()
    if not announcement:
        flash('Announcement not found.', 'danger')
        conn.close()
        return redirect(url_for('admin_announcements'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin_edit_announcement', ann_id=ann_id))
        conn.execute('UPDATE announcements SET title = ?, content = ? WHERE id = ?', (title, content, ann_id))
        conn.commit()
        conn.close()
        flash('Announcement updated successfully!', 'success')
        return redirect(url_for('admin_announcements'))

    conn.close()
    return render_template('admin_edit_announcement.html', announcement=announcement)

@app.route('/admin/announcements/delete/<int:ann_id>')
@admin_required
def admin_delete_announcement(ann_id):
    conn = get_db()
    conn.execute('DELETE FROM announcements WHERE id = ?', (ann_id,))
    conn.commit()
    conn.close()
    flash('Announcement deleted.', 'success')
    return redirect(url_for('admin_announcements'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    conn = get_db()
    if request.method == 'POST':
        basic = request.form.get('basic', '30000')
        silver = request.form.get('silver', '50000')
        gold = request.form.get('gold', '70000')
        for key, val in [('basic_price', basic), ('silver_price', silver), ('gold_price', gold)]:
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, val))
        conn.commit()
        conn.close()
        flash('Subscription prices updated!', 'success')
        return redirect(url_for('admin_settings'))

    prices = {}
    for row in conn.execute('SELECT key, value FROM settings').fetchall():
        prices[row['key']] = row['value']
    conn.close()
    return render_template('admin_settings.html', prices=prices)

# ----------------- Announcements for Users -----------------
@app.route('/announcements')
def announcements():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    announcements = conn.execute('SELECT * FROM announcements ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('announcements.html', announcements=announcements)

if __name__ == '__main__':
    app.run()            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS fee_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            payment_date TEXT DEFAULT CURRENT_DATE,
            note TEXT,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT DEFAULT CURRENT_DATE,
            status TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            ca_score REAL,
            exam_score REAL,
            total REAL,
            grade TEXT,
            term TEXT,
            session TEXT,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS class_fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(class_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reference TEXT UNIQUE NOT NULL,
            plan TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            account_number TEXT,
            account_bank TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

init_db()

# Helper functions
def get_subscription(user_id):
    conn = get_db()
    user = conn.execute('SELECT plan, subscription_start, subscription_end, student_add_count FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user

def is_subscribed(user_id):
    sub = get_subscription(user_id)
    if not sub:
        return False
    if sub['plan'] == 'premium':
        return True
    if sub['subscription_end']:
        today = date.today().isoformat()
        return today <= sub['subscription_end']
    return False

def subscription_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not is_subscribed(session['user_id']):
            flash('Please subscribe to access this feature.', 'warning')
            return redirect(url_for('subscribe'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def calculate_grade(total):
    if total >= 70:
        return 'A'
    elif total >= 60:
        return 'B'
    elif total >= 50:
        return 'C'
    elif total >= 45:
        return 'D'
    elif total >= 40:
        return 'E'
    else:
        return 'F'

# ----------------- Monnify API Helpers -----------------
def monnify_auth():
    """Get access token from Monnify."""
    url = f"{MONNIFY_BASE_URL}/api/v1/auth/login"
    auth_string = base64.b64encode(f"{MONNIFY_API_KEY}:{MONNIFY_SECRET_KEY}".encode()).decode()
    headers = {
        'Authorization': f'Basic {auth_string}',
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data['requestSuccessful']:
                return data['responseBody']['accessToken']
            else:
                print("Auth error:", data['responseMessage'])
                return None
        else:
            print("Auth HTTP error:", response.status_code, response.text)
            return None
    except Exception as e:
        print("Auth exception:", str(e))
        return None

def get_existing_virtual_account(monnify_ref):
    """Fetch an existing reserved account using its reference."""
    token = monnify_auth()
    if not token:
        raise Exception("Could not authenticate with Monnify")
    url = f"{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{monnify_ref}"
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(url, headers=headers)
    print("GET reserved account response:", response.text)
    if response.status_code == 200:
        data = response.json()
        if data['requestSuccessful']:
            body = data['responseBody']
            if body.get('accountNumber') and body.get('bankName'):
                return body
            accounts = body.get('accounts')
            if accounts and isinstance(accounts, list) and len(accounts) > 0:
                first_account = accounts[0]
                if first_account.get('accountNumber') and first_account.get('bankName'):
                    return {
                        'accountNumber': first_account['accountNumber'],
                        'bankName': first_account['bankName'],
                        'accountName': body.get('accountName'),
                        'accounts': accounts
                    }
    return None

def create_virtual_account(email, amount, reference, plan_name):
    """Create a reserved account or fetch existing one."""
    conn = get_db()
    user = conn.execute('SELECT monnify_reference FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()

    if user and user['monnify_reference']:
        existing = get_existing_virtual_account(user['monnify_reference'])
        if existing and existing.get('accountNumber') and existing.get('bankName'):
            return existing

    token = monnify_auth()
    if not token:
        raise Exception("Could not authenticate with Monnify")

    if not email:
        conn = get_db()
        user = conn.execute('SELECT email FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        if user:
            email = user['email']
        else:
            raise Exception("User email not found")

    url = f"{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    data = {
        "accountReference": reference,
        "accountName": f"EduPal {plan_name}",
        "currencyCode": "NGN",
        "contractCode": MONNIFY_CONTRACT_CODE,
        "customerEmail": email,
        "customerName": session.get('admin_name', 'User'),
        "incomeSplitConfig": [],
        "restrictPaymentSource": False,
        "getAllAvailableBanks": True,
        "amount": amount
    }
    response = requests.post(url, headers=headers, json=data)
    print("Monnify raw response:", response.text)
    if response.status_code == 200:
        resp_data = response.json()
        if resp_data['requestSuccessful']:
            body = resp_data['responseBody']
            account_number = body.get('accountNumber')
            bank_name = body.get('bankName')
            if account_number and bank_name:
                conn = get_db()
                conn.execute('UPDATE users SET monnify_reference = ? WHERE id = ?', (reference, session['user_id']))
                conn.commit()
                conn.close()
                return body
            accounts = body.get('accounts')
            if accounts and isinstance(accounts, list) and len(accounts) > 0:
                first_account = accounts[0]
                account_number = first_account.get('accountNumber')
                bank_name = first_account.get('bankName')
                if account_number and bank_name:
                    conn = get_db()
                    conn.execute('UPDATE users SET monnify_reference = ? WHERE id = ?', (reference, session['user_id']))
                    conn.commit()
                    conn.close()
                    return {
                        'accountNumber': account_number,
                        'bankName': bank_name,
                        'accountName': body.get('accountName'),
                        'accounts': accounts
                    }
            print("Parsed body:", body)
            raise Exception("Could not extract account details from Monnify response")
        else:
            raise Exception(f"Monnify error: {resp_data['responseMessage']}")
    else:
        raise Exception(f"HTTP error {response.status_code}: {response.text}")

def verify_transaction(reference):
    """Check if a transaction with given reference has been paid."""
    token = monnify_auth()
    if not token:
        return False
    url = f"{MONNIFY_BASE_URL}/api/v1/transactions/search"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    data = {
        "paymentReference": reference,
        "page": 0,
        "size": 10
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        print("Verify response:", response.text)
        if response.status_code == 200:
            resp = response.json()
            if resp['requestSuccessful']:
                transactions = resp['responseBody']['content']
                for tx in transactions:
                    if tx.get('paymentStatus') == 'PAID':
                        return True
        else:
            print("Verify HTTP error:", response.status_code, response.text)
    except Exception as e:
        print("Verify exception:", str(e))
    return False

def activate_subscription(user_id, plan):
    today = date.today()
    if plan == 'basic':
        end_date = today + timedelta(days=90)
    elif plan == 'silver':
        end_date = today + timedelta(days=180)
    elif plan == 'gold':
        end_date = today + timedelta(days=270)
    else:
        return
    conn = get_db()
    conn.execute('UPDATE users SET plan = ?, subscription_start = ?, subscription_end = ? WHERE id = ?',
                 (plan, today.isoformat(), end_date.isoformat(), user_id))
    conn.commit()
    conn.close()

# ----------------- Auth Routes -----------------
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    elif 'teacher_id' in session:
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        school_name = request.form['school_name'].strip()
        admin_name = request.form['admin_name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if not school_name or not admin_name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        conn = get_db()
        existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('An account with this email already exists. Please log in.', 'danger')
            conn.close()
            return redirect(url_for('register'))

        password_hash = generate_password_hash(password)
        if email == DEVELOPER_EMAIL:
            plan = 'premium'
            sub_start = date.today().isoformat()
            sub_end = '2099-12-31'
            student_add_count = 0
            role = 'admin'
        else:
            plan = 'trial'
            sub_start = None
            sub_end = None
            student_add_count = 0
            role = 'user'

        conn.execute(
            'INSERT INTO users (school_name, admin_name, email, password_hash, plan, subscription_start, subscription_end, student_add_count, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (school_name, admin_name, email, password_hash, plan, sub_start, sub_end, student_add_count, role)
        )
        conn.commit()
        conn.close()

        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['school_name'] = user['school_name']
            session['admin_name'] = user['admin_name']
            session['email'] = user['email']
            session['role'] = user['role']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    class_count = conn.execute('SELECT COUNT(*) FROM classes WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    fee_total = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM fee_payments WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    sub = get_subscription(session['user_id'])
    conn.close()
    today = date.today().isoformat()
    return render_template('dashboard.html', student_count=student_count, class_count=class_count, fee_total=fee_total, subscription=sub, today=today)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ----------------- Subscription Routes -----------------
@app.route('/subscribe', methods=['GET', 'POST'])
def subscribe():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Fetch current prices from settings
    conn = get_db()
    basic_price_row = conn.execute('SELECT value FROM settings WHERE key="basic_price"').fetchone()
    silver_price_row = conn.execute('SELECT value FROM settings WHERE key="silver_price"').fetchone()
    gold_price_row = conn.execute('SELECT value FROM settings WHERE key="gold_price"').fetchone()
    conn.close()

    basic_price = float(basic_price_row['value']) if basic_price_row else 30000
    silver_price = float(silver_price_row['value']) if silver_price_row else 50000
    gold_price = float(gold_price_row['value']) if gold_price_row else 70000

    if request.method == 'POST':
        plan = request.form.get('plan')
        if plan not in ['basic', 'silver', 'gold']:
            flash('Invalid plan.', 'danger')
            return redirect(url_for('subscribe'))

        amounts = {
            'basic': basic_price,
            'silver': silver_price,
            'gold': gold_price,
        }
        amount = amounts[plan]
        plan_name = {'basic': 'Basic Plan (1 Term)', 'silver': 'Silver Plan (2 Terms)', 'gold': 'Gold Plan (3 Terms)'}[plan]

        reference = f'edupal_{session["user_id"]}_{uuid.uuid4().hex[:10]}'

        try:
            account_info = create_virtual_account(session.get('email'), amount, reference, plan_name)
            account_number = account_info.get('accountNumber')
            bank_name = account_info.get('bankName')
            if not account_number or not bank_name:
                raise Exception("Missing account details in Monnify response")
            conn = get_db()
            conn.execute('''
                INSERT INTO subscriptions (user_id, reference, plan, amount, status, account_number, account_bank)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
            ''', (session['user_id'], reference, plan, amount, account_number, bank_name))
            conn.commit()
            conn.close()
            return redirect(url_for('payment_waiting', reference=reference))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(url_for('subscribe'))

    return render_template(
        'subscribe.html',
        basic_price=basic_price,
        silver_price=silver_price,
        gold_price=gold_price
    )

@app.route('/payment/waiting/<reference>')
def payment_waiting(reference):
    conn = get_db()
    sub = conn.execute('SELECT * FROM subscriptions WHERE reference = ?', (reference,)).fetchone()
    conn.close()
    if not sub:
        flash('Subscription not found.', 'danger')
        return redirect(url_for('subscribe'))
    return render_template('payment_waiting.html', sub=sub)

@app.route('/payment/confirm/<reference>')
def payment_confirm(reference):
    if verify_transaction(reference):
        conn = get_db()
        sub = conn.execute('SELECT * FROM subscriptions WHERE reference = ?', (reference,)).fetchone()
        if sub and sub['status'] == 'pending':
            activate_subscription(sub['user_id'], sub['plan'])
            conn.execute('UPDATE subscriptions SET status = "confirmed" WHERE id = ?', (sub['id'],))
            conn.commit()
            conn.close()
            flash('Payment confirmed! Subscription activated.', 'success')
            return redirect(url_for('dashboard'))
        else:
            conn.close()
            flash('Subscription already activated or invalid.', 'info')
            return redirect(url_for('dashboard'))
    else:
        flash('Payment not yet received. Please wait a few minutes or check your transfer.', 'danger')
        return redirect(url_for('payment_waiting', reference=reference))

# ----------------- Student Routes -----------------
@app.route('/students')
@subscription_required
def students():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    students_raw = conn.execute('''
        SELECT students.*, classes.name as class_name 
        FROM students 
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE students.user_id = ?
        ORDER BY students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()

    class_fees = {row['class_id']: row['amount'] for row in conn.execute(
        'SELECT class_id, amount FROM class_fees WHERE user_id = ?', (session['user_id'],)
    ).fetchall()}

    payments = {row['student_id']: row['total_paid'] for row in conn.execute(
        'SELECT student_id, SUM(amount) as total_paid FROM fee_payments WHERE user_id = ? GROUP BY student_id',
        (session['user_id'],)
    ).fetchall()}

    student_data = []
    for s in students_raw:
        student = dict(s)
        class_id = student['class_id']
        fee = class_fees.get(class_id, 0)
        paid = payments.get(student['id'], 0)
        balance = fee - paid
        student['fee'] = fee
        student['paid'] = paid
        student['balance'] = balance
        student_data.append(student)

    conn.close()
    return render_template('students.html', students=student_data)

@app.route('/students/add', methods=['GET', 'POST'])
def add_student():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    user_sub = get_subscription(session['user_id'])
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        if user_sub['plan'] == 'trial' and user_sub['student_add_count'] >= 1:
            flash('Trial allows only one student. Please subscribe to add more.', 'danger')
            return redirect(url_for('subscribe'))
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        address = request.form.get('address', '').strip()
        class_id = request.form.get('class_id') or None

        if not first_name or not last_name:
            flash('First name and last name are required.', 'danger')
        else:
            conn.execute(
                'INSERT INTO students (first_name, last_name, parent_phone, parent_email, address, class_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (first_name, last_name, parent_phone, parent_email, address, class_id, session['user_id'])
            )
            if user_sub['plan'] == 'trial':
                conn.execute('UPDATE users SET student_add_count = student_add_count + 1 WHERE id = ?', (session['user_id'],))
            conn.commit()
            flash('Student added successfully!', 'success')
            return redirect(url_for('students'))
    conn.close()
    return render_template('add_student.html', classes=classes)

@app.route('/students/edit/<int:student_id>', methods=['GET', 'POST'])
@subscription_required
def edit_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student = conn.execute(
        'SELECT * FROM students WHERE id = ? AND user_id = ?',
        (student_id, session['user_id'])
    ).fetchone()
    if not student:
        flash('Student not found.', 'danger')
        conn.close()
        return redirect(url_for('students'))

    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        address = request.form.get('address', '').strip()
        class_id = request.form.get('class_id') or None

        if not first_name or not last_name:
            flash('First name and last name are required.', 'danger')
        else:
            conn.execute(
                'UPDATE students SET first_name = ?, last_name = ?, parent_phone = ?, parent_email = ?, address = ?, class_id = ? WHERE id = ? AND user_id = ?',
                (first_name, last_name, parent_phone, parent_email, address, class_id, student_id, session['user_id'])
            )
            conn.commit()
            flash('Student updated successfully!', 'success')
            conn.close()
            return redirect(url_for('students'))
    conn.close()
    return render_template('edit_student.html', student=student, classes=classes)

@app.route('/students/delete/<int:student_id>')
@subscription_required
def delete_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student = conn.execute(
        'SELECT id FROM students WHERE id = ? AND user_id = ?',
        (student_id, session['user_id'])
    ).fetchone()
    if student:
        conn.execute('DELETE FROM fee_payments WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM attendance WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM results WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM students WHERE id = ?', (student_id,))
        conn.commit()
        flash('Student deleted.', 'success')
    else:
        flash('Student not found.', 'danger')
    conn.close()
    return redirect(url_for('students'))

# ----------------- Class Routes -----------------
@app.route('/classes')
@subscription_required
def classes():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    class_list = conn.execute('''
        SELECT classes.*, COUNT(students.id) as student_count
        FROM classes
        LEFT JOIN students ON students.class_id = classes.id
        WHERE classes.user_id = ?
        GROUP BY classes.id
        ORDER BY classes.name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('classes.html', classes=class_list)

@app.route('/classes/add', methods=['GET', 'POST'])
@subscription_required
def add_class():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Class name is required.', 'danger')
            return redirect(url_for('add_class'))
        conn = get_db()
        conn.execute('INSERT INTO classes (name, user_id) VALUES (?, ?)', (name, session['user_id']))
        conn.commit()
        conn.close()
        flash('Class added successfully!', 'success')
        return redirect(url_for('classes'))
    return render_template('add_class.html')

@app.route('/classes/delete/<int:class_id>')
@subscription_required
def delete_class(class_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE class_id = ?', (class_id,)).fetchone()[0]
    if student_count > 0:
        flash('Cannot delete class with students. Reassign students first.', 'danger')
    else:
        conn.execute('DELETE FROM class_fees WHERE class_id = ?', (class_id,))
        conn.execute('DELETE FROM teachers WHERE class_id = ?', (class_id,))
        conn.execute('DELETE FROM classes WHERE id = ? AND user_id = ?', (class_id, session['user_id']))
        conn.commit()
        flash('Class deleted.', 'success')
    conn.close()
    return redirect(url_for('classes'))

# ----------------- Fee Routes -----------------
@app.route('/fees')
@subscription_required
def fees():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    payments = conn.execute('''
        SELECT fee_payments.*, students.first_name, students.last_name, classes.name as class_name
        FROM fee_payments
        JOIN students ON fee_payments.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE fee_payments.user_id = ?
        ORDER BY fee_payments.payment_date DESC, fee_payments.id DESC
    ''', (session['user_id'],)).fetchall()
    total_collected = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM fee_payments WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    conn.close()
    return render_template('fees.html', payments=payments, total_collected=total_collected)

@app.route('/fees/add', methods=['GET', 'POST'])
@subscription_required
def add_fee():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    students = conn.execute('''
        SELECT students.id, students.first_name, students.last_name, classes.name as class_name
        FROM students
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE students.user_id = ?
        ORDER BY students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        student_id = request.form['student_id']
        amount = request.form['amount']
        note = request.form.get('note', '').strip()
        payment_date = request.form.get('payment_date')

        if not student_id or not amount:
            flash('Student and amount are required.', 'danger')
        else:
            try:
                amount = float(amount)
                if amount <= 0:
                    flash('Amount must be greater than zero.', 'danger')
                else:
                    if payment_date:
                        conn.execute('INSERT INTO fee_payments (amount, payment_date, note, student_id, user_id) VALUES (?, ?, ?, ?, ?)', (amount, payment_date, note, student_id, session['user_id']))
                    else:
                        conn.execute('INSERT INTO fee_payments (amount, note, student_id, user_id) VALUES (?, ?, ?, ?)', (amount, note, student_id, session['user_id']))
                    conn.commit()
                    flash('Fee payment recorded successfully!', 'success')
                    conn.close()
                    return redirect(url_for('fees'))
            except ValueError:
                flash('Invalid amount format.', 'danger')

    today = date.today().isoformat()
    conn.close()
    return render_template('add_fee.html', students=students, current_date=today)

@app.route('/fees/structure', methods=['GET', 'POST'])
@subscription_required
def fee_structure():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    if request.method == 'POST':
        for key, value in request.form.items():
            if key.startswith('fee_'):
                class_id = key[4:]
                amount = value.strip()
                if amount:
                    try:
                        amt = float(amount)
                        existing = conn.execute('SELECT id FROM class_fees WHERE class_id = ? AND user_id = ?', (class_id, session['user_id'])).fetchone()
                        if existing:
                            conn.execute('UPDATE class_fees SET amount = ? WHERE id = ?', (amt, existing['id']))
                        else:
                            conn.execute('INSERT INTO class_fees (class_id, amount, user_id) VALUES (?, ?, ?)', (class_id, amt, session['user_id']))
                    except ValueError:
                        flash('Invalid amount for class ID: ' + class_id, 'danger')
        conn.commit()
        conn.close()
        flash('Fee structure updated successfully!', 'success')
        return redirect(url_for('fee_structure'))

    classes = conn.execute('SELECT * FROM classes WHERE user_id = ? ORDER BY name', (session['user_id'],)).fetchall()
    class_fees = {row['class_id']: row['amount'] for row in conn.execute('SELECT class_id, amount FROM class_fees WHERE user_id = ?', (session['user_id'],)).fetchall()}
    conn.close()
    return render_template('fee_structure.html', classes=classes, class_fees=class_fees)

# ----------------- Attendance Routes (Admin) -----------------
@app.route('/attendance')
@subscription_required
def attendance():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    records = conn.execute('''
        SELECT attendance.*, students.first_name, students.last_name, classes.name as class_name
        FROM attendance
        JOIN students ON attendance.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE attendance.user_id = ?
        ORDER BY attendance.date DESC, students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('attendance.html', records=records)

@app.route('/attendance/mark', methods=['GET', 'POST'])
@subscription_required
def mark_attendance():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        class_id = request.form.get('class_id')
        attendance_date = request.form.get('attendance_date')
        if not class_id or not attendance_date:
            flash('Please select class and date.', 'danger')
            return redirect(url_for('mark_attendance'))

        students = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (class_id, session['user_id'])).fetchall()

        for student in students:
            status_key = f'status_{student["id"]}'
            status = request.form.get(status_key)
            if status:
                existing = conn.execute('SELECT id FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], attendance_date, session['user_id'])).fetchone()
                if existing:
                    conn.execute('UPDATE attendance SET status = ? WHERE id = ?', (status, existing['id']))
                else:
                    conn.execute('INSERT INTO attendance (date, status, student_id, user_id) VALUES (?, ?, ?, ?)', (attendance_date, status, student['id'], session['user_id']))
        conn.commit()
        conn.close()
        flash('Attendance saved successfully!', 'success')
        return redirect(url_for('attendance'))

    today = date.today().isoformat()
    selected_class = request.args.get('class_id')
    selected_date = request.args.get('date', today)
    students = []
    if selected_class:
        student_rows = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (selected_class, session['user_id'])).fetchall()
        for row in student_rows:
            student = dict(row)
            att = conn.execute('SELECT status FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], selected_date, session['user_id'])).fetchone()
            student['existing_status'] = att['status'] if att else None
            students.append(student)
    conn.close()
    return render_template('mark_attendance.html', classes=classes, students=students, selected_class=selected_class, selected_date=selected_date, today=today)

# ----------------- Teacher Management (Admin) -----------------
@app.route('/teachers')
@subscription_required
def teachers():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    teachers = conn.execute('''
        SELECT teachers.*, classes.name as class_name
        FROM teachers
        JOIN classes ON teachers.class_id = classes.id
        WHERE teachers.user_id = ?
        ORDER BY teachers.name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('teachers.html', teachers=teachers)

@app.route('/teachers/add', methods=['GET', 'POST'])
@subscription_required
def add_teacher():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        class_id = request.form['class_id']

        if not name or not email or not password or not class_id:
            flash('All fields are required.', 'danger')
            return redirect(url_for('add_teacher'))

        existing = conn.execute('SELECT id FROM teachers WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('A teacher with this email already exists.', 'danger')
            conn.close()
            return redirect(url_for('add_teacher'))

        password_hash = generate_password_hash(password)
        conn.execute(
            'INSERT INTO teachers (name, email, password_hash, class_id, user_id) VALUES (?, ?, ?, ?, ?)',
            (name, email, password_hash, class_id, session['user_id'])
        )
        conn.commit()
        conn.close()
        flash('Teacher account created successfully!', 'success')
        return redirect(url_for('teachers'))

    conn.close()
    return render_template('add_teacher.html', classes=classes)

@app.route('/teachers/delete/<int:teacher_id>')
@subscription_required
def delete_teacher(teacher_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    conn.execute('DELETE FROM teachers WHERE id = ? AND user_id = ?', (teacher_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('Teacher deleted.', 'success')
    return redirect(url_for('teachers'))

# ----------------- Teacher Auth & Attendance -----------------
@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db()
        teacher = conn.execute('SELECT * FROM teachers WHERE email = ?', (email,)).fetchone()
        conn.close()

        if teacher and check_password_hash(teacher['password_hash'], password):
            session['teacher_id'] = teacher['id']
            session['teacher_name'] = teacher['name']
            session['teacher_class_id'] = teacher['class_id']
            session['user_id'] = teacher['user_id']
            flash('Teacher login successful!', 'success')
            return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid teacher credentials.', 'danger')

    return render_template('teacher_login.html')

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if 'teacher_id' not in session:
        return redirect(url_for('teacher_login'))
    conn = get_db()
    class_info = conn.execute('SELECT name FROM classes WHERE id = ?', (session['teacher_class_id'],)).fetchone()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE class_id = ? AND user_id = ?', (session['teacher_class_id'], session['user_id'])).fetchone()[0]
    conn.close()
    return render_template('teacher_dashboard.html', class_name=class_info['name'] if class_info else 'Unknown', student_count=student_count)

@app.route('/teacher/attendance', methods=['GET', 'POST'])
def teacher_attendance():
    if 'teacher_id' not in session:
        return redirect(url_for('teacher_login'))

    conn = get_db()
    class_id = session['teacher_class_id']
    user_id = session['user_id']

    if request.method == 'POST':
        attendance_date = request.form.get('attendance_date')
        if not attendance_date:
            flash('Please select a date.', 'danger')
            return redirect(url_for('teacher_attendance'))

        students = conn.execute('SELECT id FROM students WHERE class_id = ? AND user_id = ?', (class_id, user_id)).fetchall()
        for student in students:
            status_key = f'status_{student["id"]}'
            status = request.form.get(status_key)
            if status:
                existing = conn.execute('SELECT id FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], attendance_date, user_id)).fetchone()
                if existing:
                    conn.execute('UPDATE attendance SET status = ? WHERE id = ?', (status, existing['id']))
                else:
                    conn.execute('INSERT INTO attendance (date, status, student_id, user_id) VALUES (?, ?, ?, ?)', (attendance_date, status, student['id'], user_id))
        conn.commit()
        conn.close()
        flash('Attendance saved successfully!', 'success')
        return redirect(url_for('teacher_dashboard'))

    today = date.today().isoformat()
    selected_date = request.args.get('date', today)
    students = []
    student_rows = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (class_id, user_id)).fetchall()
    for row in student_rows:
        student = dict(row)
        att = conn.execute('SELECT status FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], selected_date, user_id)).fetchone()
        student['existing_status'] = att['status'] if att else None
        students.append(student)

    class_name = conn.execute('SELECT name FROM classes WHERE id = ?', (class_id,)).fetchone()['name']
    conn.close()
    return render_template('teacher_attendance.html', students=students, class_name=class_name, selected_date=selected_date, today=today)

@app.route('/teacher/logout')
def teacher_logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('teacher_login'))

# ----------------- Results Routes (Admin only) -----------------
@app.route('/results')
@subscription_required
def results():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    class_id = request.args.get('class_id')
    term = request.args.get('term')
    session_year = request.args.get('session')

    query = '''
        SELECT results.*, students.first_name, students.last_name, classes.name as class_name
        FROM results
        JOIN students ON results.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE results.user_id = ?
    '''
    params = [session['user_id']]
    if class_id:
        query += ' AND students.class_id = ?'
        params.append(class_id)
    if term:
        query += ' AND results.term = ?'
        params.append(term)
    if session_year:
        query += ' AND results.session = ?'
        params.append(session_year)
    query += ' ORDER BY results.session DESC, results.term DESC, students.last_name, students.first_name, results.subject'

    records = conn.execute(query, params).fetchall()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('results.html', records=records, classes=classes, selected_class=class_id, selected_term=term, selected_session=session_year)

@app.route('/results/add', methods=['GET', 'POST'])
@subscription_required
def add_result():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        class_id = request.form.get('class_id')
        subject = request.form.get('subject').strip()
        term = request.form.get('term').strip()
        session_year = request.form.get('session').strip()

        if not class_id or not subject or not term or not session_year:
            flash('All fields are required.', 'danger')
            return redirect(url_for('add_result'))

        students = conn.execute('SELECT id FROM students WHERE class_id = ? AND user_id = ?', (class_id, session['user_id'])).fetchall()
        for student in students:
            ca_key = f'ca_{student["id"]}'
            exam_key = f'exam_{student["id"]}'
            ca_score = request.form.get(ca_key, 0) or 0
            exam_score = request.form.get(exam_key, 0) or 0
            try:
                ca = float(ca_score)
                exam = float(exam_score)
            except ValueError:
                flash('Invalid score values.', 'danger')
                conn.close()
                return redirect(url_for('add_result'))
            total = ca + exam
            grade = calculate_grade(total)
            existing = conn.execute('''SELECT id FROM results WHERE student_id = ? AND subject = ? AND term = ? AND session = ? AND user_id = ?''', (student['id'], subject, term, session_year, session['user_id'])).fetchone()
            if existing:
                conn.execute('UPDATE results SET ca_score = ?, exam_score = ?, total = ?, grade = ? WHERE id = ?', (ca, exam, total, grade, existing['id']))
            else:
                conn.execute('INSERT INTO results (subject, ca_score, exam_score, total, grade, term, session, student_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (subject, ca, exam, total, grade, term, session_year, student['id'], session['user_id']))
        conn.commit()
        conn.close()
        flash('Results saved successfully!', 'success')
        return redirect(url_for('results'))

    selected_class = request.args.get('class_id')
    students = []
    if selected_class:
        students = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (selected_class, session['user_id'])).fetchall()
    conn.close()
    today = date.today().isoformat()
    return render_template('add_result.html', classes=classes, selected_class=selected_class, students=students, today=today)

# ----------------- Admin Panel Routes -----------------
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    total_users = conn.execute('SELECT COUNT(*) FROM users WHERE role != "admin"').fetchone()[0]
    subscribed_users = conn.execute('SELECT COUNT(*) FROM users WHERE role != "admin" AND plan != "trial"').fetchone()[0]
    trial_users = total_users - subscribed_users
    conn.close()
    return render_template('admin_dashboard.html', total_users=total_users, subscribed_users=subscribed_users, trial_users=trial_users)

@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users WHERE role != "admin" ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)

@app.route('/admin/announcements')
@admin_required
def admin_announcements():
    conn = get_db()
    announcements = conn.execute('SELECT * FROM announcements ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin_announcements.html', announcements=announcements)

@app.route('/admin/announcements/add', methods=['GET', 'POST'])
@admin_required
def admin_add_announcement():
    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin_add_announcement'))
        conn = get_db()
        conn.execute('INSERT INTO announcements (title, content) VALUES (?, ?)', (title, content))
        conn.commit()
        conn.close()
        flash('Announcement posted successfully!', 'success')
        return redirect(url_for('admin_announcements'))
    return render_template('admin_add_announcement.html')

@app.route('/admin/announcements/edit/<int:ann_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_announcement(ann_id):
    conn = get_db()
    announcement = conn.execute('SELECT * FROM announcements WHERE id = ?', (ann_id,)).fetchone()
    if not announcement:
        flash('Announcement not found.', 'danger')
        conn.close()
        return redirect(url_for('admin_announcements'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin_edit_announcement', ann_id=ann_id))
        conn.execute('UPDATE announcements SET title = ?, content = ? WHERE id = ?', (title, content, ann_id))
        conn.commit()
        conn.close()
        flash('Announcement updated successfully!', 'success')
        return redirect(url_for('admin_announcements'))

    conn.close()
    return render_template('admin_edit_announcement.html', announcement=announcement)

@app.route('/admin/announcements/delete/<int:ann_id>')
@admin_required
def admin_delete_announcement(ann_id):
    conn = get_db()
    conn.execute('DELETE FROM announcements WHERE id = ?', (ann_id,))
    conn.commit()
    conn.close()
    flash('Announcement deleted.', 'success')
    return redirect(url_for('admin_announcements'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    conn = get_db()
    if request.method == 'POST':
        basic = request.form.get('basic', '30000')
        silver = request.form.get('silver', '50000')
        gold = request.form.get('gold', '70000')
        for key, val in [('basic_price', basic), ('silver_price', silver), ('gold_price', gold)]:
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, val))
        conn.commit()
        conn.close()
        flash('Subscription prices updated!', 'success')
        return redirect(url_for('admin_settings'))

    prices = {}
    for row in conn.execute('SELECT key, value FROM settings').fetchall():
        prices[row['key']] = row['value']
    conn.close()
    return render_template('admin_settings.html', prices=prices)

# ----------------- Announcements for Users -----------------
@app.route('/announcements')
def announcements():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    announcements = conn.execute('SELECT * FROM announcements ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('announcements.html', announcements=announcements)

if __name__ == '__main__':
    app.run()            address TEXT,
            class_id INTEGER,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS fee_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            payment_date TEXT DEFAULT CURRENT_DATE,
            note TEXT,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT DEFAULT CURRENT_DATE,
            status TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            ca_score REAL,
            exam_score REAL,
            total REAL,
            grade TEXT,
            term TEXT,
            session TEXT,
            student_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS class_fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(class_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reference TEXT UNIQUE NOT NULL,
            plan TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            account_number TEXT,
            account_bank TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

init_db()

# Helper functions
def get_subscription(user_id):
    conn = get_db()
    user = conn.execute('SELECT plan, subscription_start, subscription_end, student_add_count FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user

def is_subscribed(user_id):
    sub = get_subscription(user_id)
    if not sub:
        return False
    if sub['plan'] == 'premium':
        return True
    if sub['subscription_end']:
        today = date.today().isoformat()
        return today <= sub['subscription_end']
    return False

def subscription_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not is_subscribed(session['user_id']):
            flash('Please subscribe to access this feature.', 'warning')
            return redirect(url_for('subscribe'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def calculate_grade(total):
    if total >= 70:
        return 'A'
    elif total >= 60:
        return 'B'
    elif total >= 50:
        return 'C'
    elif total >= 45:
        return 'D'
    elif total >= 40:
        return 'E'
    else:
        return 'F'

# ----------------- Monnify API Helpers -----------------
def monnify_auth():
    """Get access token from Monnify."""
    url = f"{MONNIFY_BASE_URL}/api/v1/auth/login"
    auth_string = base64.b64encode(f"{MONNIFY_API_KEY}:{MONNIFY_SECRET_KEY}".encode()).decode()
    headers = {
        'Authorization': f'Basic {auth_string}',
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data['requestSuccessful']:
                return data['responseBody']['accessToken']
            else:
                print("Auth error:", data['responseMessage'])
                return None
        else:
            print("Auth HTTP error:", response.status_code, response.text)
            return None
    except Exception as e:
        print("Auth exception:", str(e))
        return None

def get_existing_virtual_account(monnify_ref):
    """Fetch an existing reserved account using its reference."""
    token = monnify_auth()
    if not token:
        raise Exception("Could not authenticate with Monnify")
    url = f"{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{monnify_ref}"
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(url, headers=headers)
    print("GET reserved account response:", response.text)
    if response.status_code == 200:
        data = response.json()
        if data['requestSuccessful']:
            body = data['responseBody']
            if body.get('accountNumber') and body.get('bankName'):
                return body
            accounts = body.get('accounts')
            if accounts and isinstance(accounts, list) and len(accounts) > 0:
                first_account = accounts[0]
                if first_account.get('accountNumber') and first_account.get('bankName'):
                    return {
                        'accountNumber': first_account['accountNumber'],
                        'bankName': first_account['bankName'],
                        'accountName': body.get('accountName'),
                        'accounts': accounts
                    }
    return None

def create_virtual_account(email, amount, reference, plan_name):
    """Create a reserved account or fetch existing one."""
    conn = get_db()
    user = conn.execute('SELECT monnify_reference FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()

    if user and user['monnify_reference']:
        existing = get_existing_virtual_account(user['monnify_reference'])
        if existing and existing.get('accountNumber') and existing.get('bankName'):
            return existing

    token = monnify_auth()
    if not token:
        raise Exception("Could not authenticate with Monnify")

    if not email:
        conn = get_db()
        user = conn.execute('SELECT email FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        if user:
            email = user['email']
        else:
            raise Exception("User email not found")

    url = f"{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    data = {
        "accountReference": reference,
        "accountName": f"EduPal {plan_name}",
        "currencyCode": "NGN",
        "contractCode": MONNIFY_CONTRACT_CODE,
        "customerEmail": email,
        "customerName": session.get('admin_name', 'User'),
        "incomeSplitConfig": [],
        "restrictPaymentSource": False,
        "getAllAvailableBanks": True,
        "amount": amount
    }
    response = requests.post(url, headers=headers, json=data)
    print("Monnify raw response:", response.text)
    if response.status_code == 200:
        resp_data = response.json()
        if resp_data['requestSuccessful']:
            body = resp_data['responseBody']
            account_number = body.get('accountNumber')
            bank_name = body.get('bankName')
            if account_number and bank_name:
                conn = get_db()
                conn.execute('UPDATE users SET monnify_reference = ? WHERE id = ?', (reference, session['user_id']))
                conn.commit()
                conn.close()
                return body
            accounts = body.get('accounts')
            if accounts and isinstance(accounts, list) and len(accounts) > 0:
                first_account = accounts[0]
                account_number = first_account.get('accountNumber')
                bank_name = first_account.get('bankName')
                if account_number and bank_name:
                    conn = get_db()
                    conn.execute('UPDATE users SET monnify_reference = ? WHERE id = ?', (reference, session['user_id']))
                    conn.commit()
                    conn.close()
                    return {
                        'accountNumber': account_number,
                        'bankName': bank_name,
                        'accountName': body.get('accountName'),
                        'accounts': accounts
                    }
            print("Parsed body:", body)
            raise Exception("Could not extract account details from Monnify response")
        else:
            raise Exception(f"Monnify error: {resp_data['responseMessage']}")
    else:
        raise Exception(f"HTTP error {response.status_code}: {response.text}")

def verify_transaction(reference):
    """Check if a transaction with given reference has been paid."""
    token = monnify_auth()
    if not token:
        return False
    url = f"{MONNIFY_BASE_URL}/api/v1/transactions/search"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    data = {
        "paymentReference": reference,
        "page": 0,
        "size": 10
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        print("Verify response:", response.text)
        if response.status_code == 200:
            resp = response.json()
            if resp['requestSuccessful']:
                transactions = resp['responseBody']['content']
                for tx in transactions:
                    if tx.get('paymentStatus') == 'PAID':
                        return True
        else:
            print("Verify HTTP error:", response.status_code, response.text)
    except Exception as e:
        print("Verify exception:", str(e))
    return False

def activate_subscription(user_id, plan):
    today = date.today()
    if plan == 'basic':
        end_date = today + timedelta(days=90)
    elif plan == 'silver':
        end_date = today + timedelta(days=180)
    elif plan == 'gold':
        end_date = today + timedelta(days=270)
    else:
        return
    conn = get_db()
    conn.execute('UPDATE users SET plan = ?, subscription_start = ?, subscription_end = ? WHERE id = ?',
                 (plan, today.isoformat(), end_date.isoformat(), user_id))
    conn.commit()
    conn.close()

# ----------------- Auth Routes -----------------
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    elif 'teacher_id' in session:
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        school_name = request.form['school_name'].strip()
        admin_name = request.form['admin_name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if not school_name or not admin_name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        conn = get_db()
        existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('An account with this email already exists. Please log in.', 'danger')
            conn.close()
            return redirect(url_for('register'))

        password_hash = generate_password_hash(password)
        if email == DEVELOPER_EMAIL:
            plan = 'premium'
            sub_start = date.today().isoformat()
            sub_end = '2099-12-31'
            student_add_count = 0
            role = 'admin'
        else:
            plan = 'trial'
            sub_start = None
            sub_end = None
            student_add_count = 0
            role = 'user'

        conn.execute(
            'INSERT INTO users (school_name, admin_name, email, password_hash, plan, subscription_start, subscription_end, student_add_count, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (school_name, admin_name, email, password_hash, plan, sub_start, sub_end, student_add_count, role)
        )
        conn.commit()
        conn.close()

        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['school_name'] = user['school_name']
            session['admin_name'] = user['admin_name']
            session['email'] = user['email']
            session['role'] = user['role']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    class_count = conn.execute('SELECT COUNT(*) FROM classes WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    fee_total = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM fee_payments WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    sub = get_subscription(session['user_id'])
    conn.close()
    today = date.today().isoformat()
    return render_template('dashboard.html', student_count=student_count, class_count=class_count, fee_total=fee_total, subscription=sub, today=today)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ----------------- Subscription Routes -----------------
@app.route('/subscribe', methods=['GET', 'POST'])
def subscribe():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        plan = request.form.get('plan')
        if plan not in ['basic', 'silver', 'gold']:
            flash('Invalid plan.', 'danger')
            return redirect(url_for('subscribe'))

        # Get dynamic prices from settings
        conn = get_db()
        basic_price = conn.execute('SELECT value FROM settings WHERE key="basic_price"').fetchone()
        silver_price = conn.execute('SELECT value FROM settings WHERE key="silver_price"').fetchone()
        gold_price = conn.execute('SELECT value FROM settings WHERE key="gold_price"').fetchone()
        conn.close()
        amounts = {
            'basic': float(basic_price['value']) if basic_price else 30000,
            'silver': float(silver_price['value']) if silver_price else 50000,
            'gold': float(gold_price['value']) if gold_price else 70000,
        }
        amount = amounts[plan]
        plan_name = {'basic': 'Basic Plan (1 Term)', 'silver': 'Silver Plan (2 Terms)', 'gold': 'Gold Plan (3 Terms)'}[plan]

        reference = f'edupal_{session["user_id"]}_{uuid.uuid4().hex[:10]}'

        try:
            account_info = create_virtual_account(session.get('email'), amount, reference, plan_name)
            account_number = account_info.get('accountNumber')
            bank_name = account_info.get('bankName')
            if not account_number or not bank_name:
                raise Exception("Missing account details in Monnify response")
            conn = get_db()
            conn.execute('''
                INSERT INTO subscriptions (user_id, reference, plan, amount, status, account_number, account_bank)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
            ''', (session['user_id'], reference, plan, amount, account_number, bank_name))
            conn.commit()
            conn.close()
            return redirect(url_for('payment_waiting', reference=reference))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(url_for('subscribe'))

    return render_template('subscribe.html')

@app.route('/payment/waiting/<reference>')
def payment_waiting(reference):
    conn = get_db()
    sub = conn.execute('SELECT * FROM subscriptions WHERE reference = ?', (reference,)).fetchone()
    conn.close()
    if not sub:
        flash('Subscription not found.', 'danger')
        return redirect(url_for('subscribe'))
    return render_template('payment_waiting.html', sub=sub)

@app.route('/payment/confirm/<reference>')
def payment_confirm(reference):
    if verify_transaction(reference):
        conn = get_db()
        sub = conn.execute('SELECT * FROM subscriptions WHERE reference = ?', (reference,)).fetchone()
        if sub and sub['status'] == 'pending':
            activate_subscription(sub['user_id'], sub['plan'])
            conn.execute('UPDATE subscriptions SET status = "confirmed" WHERE id = ?', (sub['id'],))
            conn.commit()
            conn.close()
            flash('Payment confirmed! Subscription activated.', 'success')
            return redirect(url_for('dashboard'))
        else:
            conn.close()
            flash('Subscription already activated or invalid.', 'info')
            return redirect(url_for('dashboard'))
    else:
        flash('Payment not yet received. Please wait a few minutes or check your transfer.', 'danger')
        return redirect(url_for('payment_waiting', reference=reference))

# ----------------- Student Routes -----------------
@app.route('/students')
@subscription_required
def students():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    students_raw = conn.execute('''
        SELECT students.*, classes.name as class_name 
        FROM students 
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE students.user_id = ?
        ORDER BY students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()

    class_fees = {row['class_id']: row['amount'] for row in conn.execute(
        'SELECT class_id, amount FROM class_fees WHERE user_id = ?', (session['user_id'],)
    ).fetchall()}

    payments = {row['student_id']: row['total_paid'] for row in conn.execute(
        'SELECT student_id, SUM(amount) as total_paid FROM fee_payments WHERE user_id = ? GROUP BY student_id',
        (session['user_id'],)
    ).fetchall()}

    student_data = []
    for s in students_raw:
        student = dict(s)
        class_id = student['class_id']
        fee = class_fees.get(class_id, 0)
        paid = payments.get(student['id'], 0)
        balance = fee - paid
        student['fee'] = fee
        student['paid'] = paid
        student['balance'] = balance
        student_data.append(student)

    conn.close()
    return render_template('students.html', students=student_data)

@app.route('/students/add', methods=['GET', 'POST'])
def add_student():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    user_sub = get_subscription(session['user_id'])
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        if user_sub['plan'] == 'trial' and user_sub['student_add_count'] >= 1:
            flash('Trial allows only one student. Please subscribe to add more.', 'danger')
            return redirect(url_for('subscribe'))
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        address = request.form.get('address', '').strip()
        class_id = request.form.get('class_id') or None

        if not first_name or not last_name:
            flash('First name and last name are required.', 'danger')
        else:
            conn.execute(
                'INSERT INTO students (first_name, last_name, parent_phone, parent_email, address, class_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (first_name, last_name, parent_phone, parent_email, address, class_id, session['user_id'])
            )
            if user_sub['plan'] == 'trial':
                conn.execute('UPDATE users SET student_add_count = student_add_count + 1 WHERE id = ?', (session['user_id'],))
            conn.commit()
            flash('Student added successfully!', 'success')
            return redirect(url_for('students'))
    conn.close()
    return render_template('add_student.html', classes=classes)

@app.route('/students/edit/<int:student_id>', methods=['GET', 'POST'])
@subscription_required
def edit_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student = conn.execute(
        'SELECT * FROM students WHERE id = ? AND user_id = ?',
        (student_id, session['user_id'])
    ).fetchone()
    if not student:
        flash('Student not found.', 'danger')
        conn.close()
        return redirect(url_for('students'))

    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        address = request.form.get('address', '').strip()
        class_id = request.form.get('class_id') or None

        if not first_name or not last_name:
            flash('First name and last name are required.', 'danger')
        else:
            conn.execute(
                'UPDATE students SET first_name = ?, last_name = ?, parent_phone = ?, parent_email = ?, address = ?, class_id = ? WHERE id = ? AND user_id = ?',
                (first_name, last_name, parent_phone, parent_email, address, class_id, student_id, session['user_id'])
            )
            conn.commit()
            flash('Student updated successfully!', 'success')
            conn.close()
            return redirect(url_for('students'))
    conn.close()
    return render_template('edit_student.html', student=student, classes=classes)

@app.route('/students/delete/<int:student_id>')
@subscription_required
def delete_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student = conn.execute(
        'SELECT id FROM students WHERE id = ? AND user_id = ?',
        (student_id, session['user_id'])
    ).fetchone()
    if student:
        conn.execute('DELETE FROM fee_payments WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM attendance WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM results WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM students WHERE id = ?', (student_id,))
        conn.commit()
        flash('Student deleted.', 'success')
    else:
        flash('Student not found.', 'danger')
    conn.close()
    return redirect(url_for('students'))

# ----------------- Class Routes -----------------
@app.route('/classes')
@subscription_required
def classes():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    class_list = conn.execute('''
        SELECT classes.*, COUNT(students.id) as student_count
        FROM classes
        LEFT JOIN students ON students.class_id = classes.id
        WHERE classes.user_id = ?
        GROUP BY classes.id
        ORDER BY classes.name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('classes.html', classes=class_list)

@app.route('/classes/add', methods=['GET', 'POST'])
@subscription_required
def add_class():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Class name is required.', 'danger')
            return redirect(url_for('add_class'))
        conn = get_db()
        conn.execute('INSERT INTO classes (name, user_id) VALUES (?, ?)', (name, session['user_id']))
        conn.commit()
        conn.close()
        flash('Class added successfully!', 'success')
        return redirect(url_for('classes'))
    return render_template('add_class.html')

@app.route('/classes/delete/<int:class_id>')
@subscription_required
def delete_class(class_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE class_id = ?', (class_id,)).fetchone()[0]
    if student_count > 0:
        flash('Cannot delete class with students. Reassign students first.', 'danger')
    else:
        conn.execute('DELETE FROM class_fees WHERE class_id = ?', (class_id,))
        conn.execute('DELETE FROM teachers WHERE class_id = ?', (class_id,))
        conn.execute('DELETE FROM classes WHERE id = ? AND user_id = ?', (class_id, session['user_id']))
        conn.commit()
        flash('Class deleted.', 'success')
    conn.close()
    return redirect(url_for('classes'))

# ----------------- Fee Routes -----------------
@app.route('/fees')
@subscription_required
def fees():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    payments = conn.execute('''
        SELECT fee_payments.*, students.first_name, students.last_name, classes.name as class_name
        FROM fee_payments
        JOIN students ON fee_payments.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE fee_payments.user_id = ?
        ORDER BY fee_payments.payment_date DESC, fee_payments.id DESC
    ''', (session['user_id'],)).fetchall()
    total_collected = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM fee_payments WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    conn.close()
    return render_template('fees.html', payments=payments, total_collected=total_collected)

@app.route('/fees/add', methods=['GET', 'POST'])
@subscription_required
def add_fee():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    students = conn.execute('''
        SELECT students.id, students.first_name, students.last_name, classes.name as class_name
        FROM students
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE students.user_id = ?
        ORDER BY students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        student_id = request.form['student_id']
        amount = request.form['amount']
        note = request.form.get('note', '').strip()
        payment_date = request.form.get('payment_date')

        if not student_id or not amount:
            flash('Student and amount are required.', 'danger')
        else:
            try:
                amount = float(amount)
                if amount <= 0:
                    flash('Amount must be greater than zero.', 'danger')
                else:
                    if payment_date:
                        conn.execute('INSERT INTO fee_payments (amount, payment_date, note, student_id, user_id) VALUES (?, ?, ?, ?, ?)', (amount, payment_date, note, student_id, session['user_id']))
                    else:
                        conn.execute('INSERT INTO fee_payments (amount, note, student_id, user_id) VALUES (?, ?, ?, ?)', (amount, note, student_id, session['user_id']))
                    conn.commit()
                    flash('Fee payment recorded successfully!', 'success')
                    conn.close()
                    return redirect(url_for('fees'))
            except ValueError:
                flash('Invalid amount format.', 'danger')

    today = date.today().isoformat()
    conn.close()
    return render_template('add_fee.html', students=students, current_date=today)

@app.route('/fees/structure', methods=['GET', 'POST'])
@subscription_required
def fee_structure():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    if request.method == 'POST':
        for key, value in request.form.items():
            if key.startswith('fee_'):
                class_id = key[4:]
                amount = value.strip()
                if amount:
                    try:
                        amt = float(amount)
                        existing = conn.execute('SELECT id FROM class_fees WHERE class_id = ? AND user_id = ?', (class_id, session['user_id'])).fetchone()
                        if existing:
                            conn.execute('UPDATE class_fees SET amount = ? WHERE id = ?', (amt, existing['id']))
                        else:
                            conn.execute('INSERT INTO class_fees (class_id, amount, user_id) VALUES (?, ?, ?)', (class_id, amt, session['user_id']))
                    except ValueError:
                        flash('Invalid amount for class ID: ' + class_id, 'danger')
        conn.commit()
        conn.close()
        flash('Fee structure updated successfully!', 'success')
        return redirect(url_for('fee_structure'))

    classes = conn.execute('SELECT * FROM classes WHERE user_id = ? ORDER BY name', (session['user_id'],)).fetchall()
    class_fees = {row['class_id']: row['amount'] for row in conn.execute('SELECT class_id, amount FROM class_fees WHERE user_id = ?', (session['user_id'],)).fetchall()}
    conn.close()
    return render_template('fee_structure.html', classes=classes, class_fees=class_fees)

# ----------------- Attendance Routes (Admin) -----------------
@app.route('/attendance')
@subscription_required
def attendance():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    records = conn.execute('''
        SELECT attendance.*, students.first_name, students.last_name, classes.name as class_name
        FROM attendance
        JOIN students ON attendance.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE attendance.user_id = ?
        ORDER BY attendance.date DESC, students.last_name, students.first_name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('attendance.html', records=records)

@app.route('/attendance/mark', methods=['GET', 'POST'])
@subscription_required
def mark_attendance():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()

    if request.method == 'POST':
        class_id = request.form.get('class_id')
        attendance_date = request.form.get('attendance_date')
        if not class_id or not attendance_date:
            flash('Please select class and date.', 'danger')
            return redirect(url_for('mark_attendance'))

        students = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (class_id, session['user_id'])).fetchall()

        for student in students:
            status_key = f'status_{student["id"]}'
            status = request.form.get(status_key)
            if status:
                existing = conn.execute('SELECT id FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], attendance_date, session['user_id'])).fetchone()
                if existing:
                    conn.execute('UPDATE attendance SET status = ? WHERE id = ?', (status, existing['id']))
                else:
                    conn.execute('INSERT INTO attendance (date, status, student_id, user_id) VALUES (?, ?, ?, ?)', (attendance_date, status, student['id'], session['user_id']))
        conn.commit()
        conn.close()
        flash('Attendance saved successfully!', 'success')
        return redirect(url_for('attendance'))

    today = date.today().isoformat()
    selected_class = request.args.get('class_id')
    selected_date = request.args.get('date', today)
    students = []
    if selected_class:
        student_rows = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (selected_class, session['user_id'])).fetchall()
        for row in student_rows:
            student = dict(row)
            att = conn.execute('SELECT status FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], selected_date, session['user_id'])).fetchone()
            student['existing_status'] = att['status'] if att else None
            students.append(student)
    conn.close()
    return render_template('mark_attendance.html', classes=classes, students=students, selected_class=selected_class, selected_date=selected_date, today=today)

# ----------------- Teacher Management (Admin) -----------------
@app.route('/teachers')
@subscription_required
def teachers():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    teachers = conn.execute('''
        SELECT teachers.*, classes.name as class_name
        FROM teachers
        JOIN classes ON teachers.class_id = classes.id
        WHERE teachers.user_id = ?
        ORDER BY teachers.name
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('teachers.html', teachers=teachers)

@app.route('/teachers/add', methods=['GET', 'POST'])
@subscription_required
def add_teacher():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        class_id = request.form['class_id']

        if not name or not email or not password or not class_id:
            flash('All fields are required.', 'danger')
            return redirect(url_for('add_teacher'))

        existing = conn.execute('SELECT id FROM teachers WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('A teacher with this email already exists.', 'danger')
            conn.close()
            return redirect(url_for('add_teacher'))

        password_hash = generate_password_hash(password)
        conn.execute(
            'INSERT INTO teachers (name, email, password_hash, class_id, user_id) VALUES (?, ?, ?, ?, ?)',
            (name, email, password_hash, class_id, session['user_id'])
        )
        conn.commit()
        conn.close()
        flash('Teacher account created successfully!', 'success')
        return redirect(url_for('teachers'))

    conn.close()
    return render_template('add_teacher.html', classes=classes)

@app.route('/teachers/delete/<int:teacher_id>')
@subscription_required
def delete_teacher(teacher_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    conn.execute('DELETE FROM teachers WHERE id = ? AND user_id = ?', (teacher_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('Teacher deleted.', 'success')
    return redirect(url_for('teachers'))

# ----------------- Teacher Auth & Attendance -----------------
@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db()
        teacher = conn.execute('SELECT * FROM teachers WHERE email = ?', (email,)).fetchone()
        conn.close()

        if teacher and check_password_hash(teacher['password_hash'], password):
            session['teacher_id'] = teacher['id']
            session['teacher_name'] = teacher['name']
            session['teacher_class_id'] = teacher['class_id']
            session['user_id'] = teacher['user_id']
            flash('Teacher login successful!', 'success')
            return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid teacher credentials.', 'danger')

    return render_template('teacher_login.html')

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if 'teacher_id' not in session:
        return redirect(url_for('teacher_login'))
    conn = get_db()
    class_info = conn.execute('SELECT name FROM classes WHERE id = ?', (session['teacher_class_id'],)).fetchone()
    student_count = conn.execute('SELECT COUNT(*) FROM students WHERE class_id = ? AND user_id = ?', (session['teacher_class_id'], session['user_id'])).fetchone()[0]
    conn.close()
    return render_template('teacher_dashboard.html', class_name=class_info['name'] if class_info else 'Unknown', student_count=student_count)

@app.route('/teacher/attendance', methods=['GET', 'POST'])
def teacher_attendance():
    if 'teacher_id' not in session:
        return redirect(url_for('teacher_login'))

    conn = get_db()
    class_id = session['teacher_class_id']
    user_id = session['user_id']

    if request.method == 'POST':
        attendance_date = request.form.get('attendance_date')
        if not attendance_date:
            flash('Please select a date.', 'danger')
            return redirect(url_for('teacher_attendance'))

        students = conn.execute('SELECT id FROM students WHERE class_id = ? AND user_id = ?', (class_id, user_id)).fetchall()
        for student in students:
            status_key = f'status_{student["id"]}'
            status = request.form.get(status_key)
            if status:
                existing = conn.execute('SELECT id FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], attendance_date, user_id)).fetchone()
                if existing:
                    conn.execute('UPDATE attendance SET status = ? WHERE id = ?', (status, existing['id']))
                else:
                    conn.execute('INSERT INTO attendance (date, status, student_id, user_id) VALUES (?, ?, ?, ?)', (attendance_date, status, student['id'], user_id))
        conn.commit()
        conn.close()
        flash('Attendance saved successfully!', 'success')
        return redirect(url_for('teacher_dashboard'))

    today = date.today().isoformat()
    selected_date = request.args.get('date', today)
    students = []
    student_rows = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (class_id, user_id)).fetchall()
    for row in student_rows:
        student = dict(row)
        att = conn.execute('SELECT status FROM attendance WHERE student_id = ? AND date = ? AND user_id = ?', (student['id'], selected_date, user_id)).fetchone()
        student['existing_status'] = att['status'] if att else None
        students.append(student)

    class_name = conn.execute('SELECT name FROM classes WHERE id = ?', (class_id,)).fetchone()['name']
    conn.close()
    return render_template('teacher_attendance.html', students=students, class_name=class_name, selected_date=selected_date, today=today)

@app.route('/teacher/logout')
def teacher_logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('teacher_login'))

# ----------------- Results Routes (Admin only) -----------------
@app.route('/results')
@subscription_required
def results():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    class_id = request.args.get('class_id')
    term = request.args.get('term')
    session_year = request.args.get('session')

    query = '''
        SELECT results.*, students.first_name, students.last_name, classes.name as class_name
        FROM results
        JOIN students ON results.student_id = students.id
        LEFT JOIN classes ON students.class_id = classes.id
        WHERE results.user_id = ?
    '''
    params = [session['user_id']]
    if class_id:
        query += ' AND students.class_id = ?'
        params.append(class_id)
    if term:
        query += ' AND results.term = ?'
        params.append(term)
    if session_year:
        query += ' AND results.session = ?'
        params.append(session_year)
    query += ' ORDER BY results.session DESC, results.term DESC, students.last_name, students.first_name, results.subject'

    records = conn.execute(query, params).fetchall()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('results.html', records=records, classes=classes, selected_class=class_id, selected_term=term, selected_session=session_year)

@app.route('/results/add', methods=['GET', 'POST'])
@subscription_required
def add_result():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    classes = conn.execute('SELECT * FROM classes WHERE user_id = ?', (session['user_id'],)).fetchall()
    if request.method == 'POST':
        class_id = request.form.get('class_id')
        subject = request.form.get('subject').strip()
        term = request.form.get('term').strip()
        session_year = request.form.get('session').strip()

        if not class_id or not subject or not term or not session_year:
            flash('All fields are required.', 'danger')
            return redirect(url_for('add_result'))

        students = conn.execute('SELECT id FROM students WHERE class_id = ? AND user_id = ?', (class_id, session['user_id'])).fetchall()
        for student in students:
            ca_key = f'ca_{student["id"]}'
            exam_key = f'exam_{student["id"]}'
            ca_score = request.form.get(ca_key, 0) or 0
            exam_score = request.form.get(exam_key, 0) or 0
            try:
                ca = float(ca_score)
                exam = float(exam_score)
            except ValueError:
                flash('Invalid score values.', 'danger')
                conn.close()
                return redirect(url_for('add_result'))
            total = ca + exam
            grade = calculate_grade(total)
            existing = conn.execute('''SELECT id FROM results WHERE student_id = ? AND subject = ? AND term = ? AND session = ? AND user_id = ?''', (student['id'], subject, term, session_year, session['user_id'])).fetchone()
            if existing:
                conn.execute('UPDATE results SET ca_score = ?, exam_score = ?, total = ?, grade = ? WHERE id = ?', (ca, exam, total, grade, existing['id']))
            else:
                conn.execute('INSERT INTO results (subject, ca_score, exam_score, total, grade, term, session, student_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (subject, ca, exam, total, grade, term, session_year, student['id'], session['user_id']))
        conn.commit()
        conn.close()
        flash('Results saved successfully!', 'success')
        return redirect(url_for('results'))

    selected_class = request.args.get('class_id')
    students = []
    if selected_class:
        students = conn.execute('SELECT id, first_name, last_name FROM students WHERE class_id = ? AND user_id = ? ORDER BY last_name, first_name', (selected_class, session['user_id'])).fetchall()
    conn.close()
    today = date.today().isoformat()
    return render_template('add_result.html', classes=classes, selected_class=selected_class, students=students, today=today)

# ----------------- Admin Panel Routes -----------------
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    total_users = conn.execute('SELECT COUNT(*) FROM users WHERE role != "admin"').fetchone()[0]
    subscribed_users = conn.execute('SELECT COUNT(*) FROM users WHERE role != "admin" AND plan != "trial"').fetchone()[0]
    trial_users = total_users - subscribed_users
    conn.close()
    return render_template('admin_dashboard.html', total_users=total_users, subscribed_users=subscribed_users, trial_users=trial_users)

@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users WHERE role != "admin" ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)

@app.route('/admin/announcements')
@admin_required
def admin_announcements():
    conn = get_db()
    announcements = conn.execute('SELECT * FROM announcements ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin_announcements.html', announcements=announcements)

@app.route('/admin/announcements/add', methods=['GET', 'POST'])
@admin_required
def admin_add_announcement():
    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin_add_announcement'))
        conn = get_db()
        conn.execute('INSERT INTO announcements (title, content) VALUES (?, ?)', (title, content))
        conn.commit()
        conn.close()
        flash('Announcement posted successfully!', 'success')
        return redirect(url_for('admin_announcements'))
    return render_template('admin_add_announcement.html')

@app.route('/admin/announcements/edit/<int:ann_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_announcement(ann_id):
    conn = get_db()
    announcement = conn.execute('SELECT * FROM announcements WHERE id = ?', (ann_id,)).fetchone()
    if not announcement:
        flash('Announcement not found.', 'danger')
        conn.close()
        return redirect(url_for('admin_announcements'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin_edit_announcement', ann_id=ann_id))
        conn.execute('UPDATE announcements SET title = ?, content = ? WHERE id = ?', (title, content, ann_id))
        conn.commit()
        conn.close()
        flash('Announcement updated successfully!', 'success')
        return redirect(url_for('admin_announcements'))

    conn.close()
    return render_template('admin_edit_announcement.html', announcement=announcement)

@app.route('/admin/announcements/delete/<int:ann_id>')
@admin_required
def admin_delete_announcement(ann_id):
    conn = get_db()
    conn.execute('DELETE FROM announcements WHERE id = ?', (ann_id,))
    conn.commit()
    conn.close()
    flash('Announcement deleted.', 'success')
    return redirect(url_for('admin_announcements'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    conn = get_db()
    if request.method == 'POST':
        basic = request.form.get('basic', '30000')
        silver = request.form.get('silver', '50000')
        gold = request.form.get('gold', '70000')
        for key, val in [('basic_price', basic), ('silver_price', silver), ('gold_price', gold)]:
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, val))
        conn.commit()
        conn.close()
        flash('Subscription prices updated!', 'success')
        return redirect(url_for('admin_settings'))

    prices = {}
    for row in conn.execute('SELECT key, value FROM settings').fetchall():
        prices[row['key']] = row['value']
    conn.close()
    return render_template('admin_settings.html', prices=prices)

# ----------------- Announcements for Users -----------------
@app.route('/announcements')
def announcements():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    announcements = conn.execute('SELECT * FROM announcements ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('announcements.html', announcements=announcements)

if __name__ == '__main__':
    app.run()
