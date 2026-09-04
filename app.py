from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta
from functools import wraps
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

DATABASE_URL = os.environ.get('DATABASE_URL')
USING_POSTGRES = bool(DATABASE_URL)

DATABASE = 'edupal.db'
DEVELOPER_EMAIL = os.environ.get('DEVELOPER_EMAIL', 'taliatibrahim457@gmail.com')

# Default bank details
DEFAULT_BANK_NAME = 'Moniepoint'
DEFAULT_BANK_ACCOUNT = '9016530108'
DEFAULT_BANK_ACCOUNT_NAME = 'Taliat Ibrahim Olasunkanmi'

class PostgresDB:
    def __init__(self, conn, cur):
        self.conn = conn
        self.cur = cur
    def execute(self, sql, params=()):
        sql = sql.replace('?', '%s')
        self.cur.execute(sql, params)
        return self.cur
    def commit(self):
        self.conn.commit()
    def close(self):
        self.cur.close()
        self.conn.close()

def get_db():
    if USING_POSTGRES:
        db_url = DATABASE_URL
        if 'sslmode' not in db_url:
            separator = '&' if '?' in db_url else '?'
            db_url += f'{separator}sslmode=require'
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.DictCursor)
        cur = conn.cursor()
        return PostgresDB(conn, cur)
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db()
    if USING_POSTGRES:
        conn.execute('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, school_name TEXT NOT NULL, admin_name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, plan TEXT DEFAULT %s, subscription_start TEXT, subscription_end TEXT, student_add_count INTEGER DEFAULT 0, role TEXT DEFAULT %s)', ('trial', 'user'))
        conn.execute('CREATE TABLE IF NOT EXISTS classes (id SERIAL PRIMARY KEY, name TEXT NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS students (id SERIAL PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL, parent_phone TEXT, parent_email TEXT, address TEXT, class_id INTEGER, user_id INTEGER NOT NULL, FOREIGN KEY (class_id) REFERENCES classes (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS fee_payments (id SERIAL PRIMARY KEY, amount REAL NOT NULL, payment_date TEXT DEFAULT CURRENT_DATE, note TEXT, student_id INTEGER NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (student_id) REFERENCES students (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS attendance (id SERIAL PRIMARY KEY, date TEXT DEFAULT CURRENT_DATE, status TEXT NOT NULL, student_id INTEGER NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (student_id) REFERENCES students (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS results (id SERIAL PRIMARY KEY, subject TEXT NOT NULL, ca_score REAL, exam_score REAL, total REAL, grade TEXT, term TEXT, session TEXT, student_id INTEGER NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (student_id) REFERENCES students (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS class_fees (id SERIAL PRIMARY KEY, class_id INTEGER NOT NULL, amount REAL NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (class_id) REFERENCES classes (id), FOREIGN KEY (user_id) REFERENCES users (id), UNIQUE(class_id, user_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS teachers (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, class_id INTEGER NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (class_id) REFERENCES classes (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS subscriptions (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, reference TEXT UNIQUE NOT NULL, plan TEXT NOT NULL, amount REAL NOT NULL, status TEXT DEFAULT %s, account_number TEXT, account_bank TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id))', ('pending',))
        conn.execute('CREATE TABLE IF NOT EXISTS announcements (id SERIAL PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS pending_subscriptions (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, plan TEXT NOT NULL, amount REAL NOT NULL, reference_text TEXT, status TEXT DEFAULT %s, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id))', ('pending',))
    else:
        conn.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, school_name TEXT NOT NULL, admin_name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, plan TEXT DEFAULT "trial", subscription_start TEXT, subscription_end TEXT, student_add_count INTEGER DEFAULT 0, role TEXT DEFAULT "user")')
        conn.execute('CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT NOT NULL, last_name TEXT NOT NULL, parent_phone TEXT, parent_email TEXT, address TEXT, class_id INTEGER, user_id INTEGER NOT NULL, FOREIGN KEY (class_id) REFERENCES classes (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS fee_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL NOT NULL, payment_date TEXT DEFAULT CURRENT_DATE, note TEXT, student_id INTEGER NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (student_id) REFERENCES students (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT DEFAULT CURRENT_DATE, status TEXT NOT NULL, student_id INTEGER NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (student_id) REFERENCES students (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, ca_score REAL, exam_score REAL, total REAL, grade TEXT, term TEXT, session TEXT, student_id INTEGER NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (student_id) REFERENCES students (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS class_fees (id INTEGER PRIMARY KEY AUTOINCREMENT, class_id INTEGER NOT NULL, amount REAL NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (class_id) REFERENCES classes (id), FOREIGN KEY (user_id) REFERENCES users (id), UNIQUE(class_id, user_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, class_id INTEGER NOT NULL, user_id INTEGER NOT NULL, FOREIGN KEY (class_id) REFERENCES classes (id), FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, reference TEXT UNIQUE NOT NULL, plan TEXT NOT NULL, amount REAL NOT NULL, status TEXT DEFAULT "pending", account_number TEXT, account_bank TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id))')
        conn.execute('CREATE TABLE IF NOT EXISTS announcements (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS pending_subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, plan TEXT NOT NULL, amount REAL NOT NULL, reference_text TEXT, status TEXT DEFAULT "pending", created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id))')

    defaults = {
        'basic_price': '30000',
        'silver_price': '50000',
        'gold_price': '70000',
        'bank_name': DEFAULT_BANK_NAME,
        'bank_account': DEFAULT_BANK_ACCOUNT,
        'bank_account_name': DEFAULT_BANK_ACCOUNT_NAME
    }
    for key, val in defaults.items():
        if USING_POSTGRES:
            conn.execute('INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', (key, val))
        else:
            conn.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, val))
    conn.commit()
    conn.close()

init_db()

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
    conn.execute('UPDATE users SET plan = ?, subscription_start = ?, subscription_end = ? WHERE id = ?', (plan, today.isoformat(), end_date.isoformat(), user_id))
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
        conn.execute('INSERT INTO users (school_name, admin_name, email, password_hash, plan, subscription_start, subscription_end, student_add_count, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (school_name, admin_name, email, password_hash, plan, sub_start, sub_end, student_add_count, role))
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
    conn = get_db()
    basic_price_row = conn.execute('SELECT value FROM settings WHERE key=?', ('basic_price',)).fetchone()
    silver_price_row = conn.execute('SELECT value FROM settings WHERE key=?', ('silver_price',)).fetchone()
    gold_price_row = conn.execute('SELECT value FROM settings WHERE key=?', ('gold_price',)).fetchone()
    bank_name = conn.execute('SELECT value FROM settings WHERE key=?', ('bank_name',)).fetchone()
    bank_account = conn.execute('SELECT value FROM settings WHERE key=?', ('bank_account',)).fetchone()
    bank_account_name = conn.execute('SELECT value FROM settings WHERE key=?', ('bank_account_name',)).fetchone()
    conn.close()
    basic_price = float(basic_price_row['value']) if basic_price_row else 30000
    silver_price = float(silver_price_row['value']) if silver_price_row else 50000
    gold_price = float(gold_price_row['value']) if gold_price_row else 70000
    bank_details = {
        'bank_name': bank_name['value'] if bank_name else DEFAULT_BANK_NAME,
        'bank_account': bank_account['value'] if bank_account else DEFAULT_BANK_ACCOUNT,
        'bank_account_name': bank_account_name['value'] if bank_account_name else DEFAULT_BANK_ACCOUNT_NAME
    }
    if request.method == 'POST':
        plan = request.form.get('plan')
        reference_text = request.form.get('reference_text', '').strip()
        if plan not in ['basic', 'silver', 'gold']:
            flash('Invalid plan.', 'danger')
            return redirect(url_for('subscribe'))
        if not reference_text:
            flash('Please enter the transfer reference or sender name.', 'danger')
            return redirect(url_for('subscribe'))
        amounts = {'basic': basic_price, 'silver': silver_price, 'gold': gold_price}
        amount = amounts[plan]
        conn = get_db()
        conn.execute('INSERT INTO pending_subscriptions (user_id, plan, amount, reference_text, status) VALUES (?, ?, ?, ?, ?)', (session['user_id'], plan, amount, reference_text, 'pending'))
        conn.commit()
        conn.close()
        flash('Your payment has been submitted for approval. You will be notified once activated.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('subscribe.html', basic_price=basic_price, silver_price=silver_price, gold_price=gold_price, bank_details=bank_details)

# ----------------- Admin Manual Payment Approval -----------------
@app.route('/admin/pending_payments')
@admin_required
def admin_pending_payments():
    conn = get_db()
    pending = conn.execute('''
        SELECT pending_subscriptions.*, users.school_name, users.email
        FROM pending_subscriptions
        JOIN users ON pending_subscriptions.user_id = users.id
        WHERE pending_subscriptions.status = ?
        ORDER BY pending_subscriptions.id DESC
    ''', ('pending',)).fetchall()
    conn.close()
    return render_template('admin_pending_payments.html', pending=pending)

@app.route('/admin/approve_payment/<int:payment_id>')
@admin_required
def admin_approve_payment(payment_id):
    conn = get_db()
    payment = conn.execute('SELECT * FROM pending_subscriptions WHERE id = ?', (payment_id,)).fetchone()
    if payment:
        activate_subscription(payment['user_id'], payment['plan'])
        conn.execute('UPDATE pending_subscriptions SET status = ? WHERE id = ?', ('approved', payment_id))
        conn.commit()
        conn.close()
        flash('Payment approved and subscription activated.', 'success')
    else:
        conn.close()
        flash('Payment not found.', 'danger')
    return redirect(url_for('admin_pending_payments'))

@app.route('/admin/reject_payment/<int:payment_id>')
@admin_required
def admin_reject_payment(payment_id):
    conn = get_db()
    conn.execute('UPDATE pending_subscriptions SET status = ? WHERE id = ?', ('rejected', payment_id))
    conn.commit()
    conn.close()
    flash('Payment rejected.', 'info')
    return redirect(url_for('admin_pending_payments'))

# ----------------- Cancel Subscription -----------------
@app.route('/admin/cancel_subscription/<int:user_id>')
@admin_required
def admin_cancel_subscription(user_id):
    conn = get_db()
    conn.execute('UPDATE users SET plan = ?, subscription_start = NULL, subscription_end = NULL WHERE id = ?', ('trial', user_id))
    conn.commit()
    conn.close()
    flash('Subscription cancelled.', 'success')
    return redirect(url_for('admin_users'))

# ----------------- Admin Panel Routes -----------------
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    total_users = conn.execute('SELECT COUNT(*) FROM users WHERE role != ?', ('admin',)).fetchone()[0]
    subscribed_users = conn.execute('SELECT COUNT(*) FROM users WHERE role != ? AND plan != ?', ('admin', 'trial')).fetchone()[0]
    trial_users = total_users - subscribed_users
    pending_count = conn.execute('SELECT COUNT(*) FROM pending_subscriptions WHERE status = ?', ('pending',)).fetchone()[0]
    conn.close()
    return render_template('admin_dashboard.html', total_users=total_users, subscribed_users=subscribed_users, trial_users=trial_users, pending_count=pending_count)

@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users WHERE role != ? ORDER BY id DESC', ('admin',)).fetchall()
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
        bank_name = request.form.get('bank_name', '')
        bank_account = request.form.get('bank_account', '')
        bank_account_name = request.form.get('bank_account_name', '')
        for key, val in [('basic_price', basic), ('silver_price', silver), ('gold_price', gold), ('bank_name', bank_name), ('bank_account', bank_account), ('bank_account_name', bank_account_name)]:
            if USING_POSTGRES:
                conn.execute('INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', (key, val))
            else:
                conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, val))
        conn.commit()
        conn.close()
        flash('Settings updated!', 'success')
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

# ----------------- Student Routes -----------------
@app.route('/students')
@subscription_required
def students():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    students_raw = conn.execute('SELECT students.*, classes.name as class_name FROM students LEFT JOIN classes ON students.class_id = classes.id WHERE students.user_id = ? ORDER BY students.last_name, students.first_name', (session['user_id'],)).fetchall()
    class_fees = {row['class_id']: row['amount'] for row in conn.execute('SELECT class_id, amount FROM class_fees WHERE user_id = ?', (session['user_id'],)).fetchall()}
    payments = {row['student_id']: row['total_paid'] for row in conn.execute('SELECT student_id, SUM(amount) as total_paid FROM fee_payments WHERE user_id = ? GROUP BY student_id', (session['user_id'],)).fetchall()}
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
            conn.execute('INSERT INTO students (first_name, last_name, parent_phone, parent_email, address, class_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)', (first_name, last_name, parent_phone, parent_email, address, class_id, session['user_id']))
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
    student = conn.execute('SELECT * FROM students WHERE id = ? AND user_id = ?', (student_id, session['user_id'])).fetchone()
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
            conn.execute('UPDATE students SET first_name = ?, last_name = ?, parent_phone = ?, parent_email = ?, address = ?, class_id = ? WHERE id = ? AND user_id = ?', (first_name, last_name, parent_phone, parent_email, address, class_id, student_id, session['user_id']))
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
    student = conn.execute('SELECT id FROM students WHERE id = ? AND user_id = ?', (student_id, session['user_id'])).fetchone()
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
    class_list = conn.execute('SELECT classes.*, COUNT(students.id) as student_count FROM classes LEFT JOIN students ON students.class_id = classes.id WHERE classes.user_id = ? GROUP BY classes.id ORDER BY classes.name', (session['user_id'],)).fetchall()
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
    payments = conn.execute('SELECT fee_payments.*, students.first_name, students.last_name, classes.name as class_name FROM fee_payments JOIN students ON fee_payments.student_id = students.id LEFT JOIN classes ON students.class_id = classes.id WHERE fee_payments.user_id = ? ORDER BY fee_payments.payment_date DESC, fee_payments.id DESC', (session['user_id'],)).fetchall()
    total_collected = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM fee_payments WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    conn.close()
    return render_template('fees.html', payments=payments, total_collected=total_collected)

@app.route('/fees/add', methods=['GET', 'POST'])
@subscription_required
def add_fee():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    students = conn.execute('SELECT students.id, students.first_name, students.last_name, classes.name as class_name FROM students LEFT JOIN classes ON students.class_id = classes.id WHERE students.user_id = ? ORDER BY students.last_name, students.first_name', (session['user_id'],)).fetchall()
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
    records = conn.execute('SELECT attendance.*, students.first_name, students.last_name, classes.name as class_name FROM attendance JOIN students ON attendance.student_id = students.id LEFT JOIN classes ON students.class_id = classes.id WHERE attendance.user_id = ? ORDER BY attendance.date DESC, students.last_name, students.first_name', (session['user_id'],)).fetchall()
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
    teachers = conn.execute('SELECT teachers.*, classes.name as class_name FROM teachers JOIN classes ON teachers.class_id = classes.id WHERE teachers.user_id = ? ORDER BY teachers.name', (session['user_id'],)).fetchall()
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
        conn.execute('INSERT INTO teachers (name, email, password_hash, class_id, user_id) VALUES (?, ?, ?, ?, ?)', (name, email, password_hash, class_id, session['user_id']))
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
    query = 'SELECT results.*, students.first_name, students.last_name, classes.name as class_name FROM results JOIN students ON results.student_id = students.id LEFT JOIN classes ON students.class_id = classes.id WHERE results.user_id = ?'
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
            existing = conn.execute('SELECT id FROM results WHERE student_id = ? AND subject = ? AND term = ? AND session = ? AND user_id = ?', (student['id'], subject, term, session_year, session['user_id'])).fetchone()
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

if __name__ == '__main__':
    app.run()
