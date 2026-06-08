import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL', '')


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                line_user_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                hourly_wage INTEGER DEFAULT 200,
                shift_start TEXT DEFAULT '08:00',
                shift_end TEXT DEFAULT '17:00',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                date TEXT NOT NULL,
                punch_in TEXT,
                punch_out TEXT,
                late_minutes INTEGER DEFAULT 0,
                overtime_minutes INTEGER DEFAULT 0,
                UNIQUE(employee_id, date)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS temp_state (
                line_user_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                data TEXT DEFAULT ''
            )
        """)
        cur.execute("INSERT INTO config (key, value) VALUES ('boss_line_id', '') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO config (key, value) VALUES ('default_shift_start', '08:00') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO config (key, value) VALUES ('default_shift_end', '17:00') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO config (key, value) VALUES ('default_hourly_wage', '200') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO config (key, value) VALUES ('late_grace_minutes', '5') ON CONFLICT DO NOTHING")
        conn.commit()
    finally:
        conn.close()


def get_config(key):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT value FROM config WHERE key = %s", (key,))
        row = cur.fetchone()
        return row['value'] if row else None
    finally:
        conn.close()


def set_config(key, value):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
            (key, value, value)
        )
        conn.commit()
    finally:
        conn.close()


def get_employee_by_line_id(line_user_id):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM employees WHERE line_user_id = %s AND is_active = TRUE", (line_user_id,))
        return cur.fetchone()
    finally:
        conn.close()


def get_employee_by_name(name):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM employees WHERE name = %s AND is_active = TRUE", (name,))
        return cur.fetchone()
    finally:
        conn.close()


def get_all_employees():
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM employees WHERE is_active = TRUE ORDER BY name")
        return cur.fetchall()
    finally:
        conn.close()


def add_employee(line_user_id, name, hourly_wage=None, shift_start=None, shift_end=None):
    if hourly_wage is None:
        hourly_wage = int(get_config('default_hourly_wage') or 200)
    if shift_start is None:
        shift_start = get_config('default_shift_start') or '08:00'
    if shift_end is None:
        shift_end = get_config('default_shift_end') or '17:00'

    import pytz
    from datetime import datetime
    created_at = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO employees (line_user_id, name, hourly_wage, shift_start, shift_end, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (line_user_id) DO UPDATE SET name = %s, is_active = TRUE""",
            (line_user_id, name, hourly_wage, shift_start, shift_end, created_at, name)
        )
        conn.commit()
    finally:
        conn.close()


def get_today_attendance(employee_id, date_str):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM attendance WHERE employee_id = %s AND date = %s", (employee_id, date_str))
        return cur.fetchone()
    finally:
        conn.close()


def punch_in(employee_id, date_str, time_str, late_minutes):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO attendance (employee_id, date, punch_in, late_minutes)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (employee_id, date) DO UPDATE SET punch_in = %s, late_minutes = %s""",
            (employee_id, date_str, time_str, late_minutes, time_str, late_minutes)
        )
        conn.commit()
    finally:
        conn.close()


def punch_out(employee_id, date_str, time_str, overtime_minutes):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE attendance SET punch_out = %s, overtime_minutes = %s WHERE employee_id = %s AND date = %s",
            (time_str, overtime_minutes, employee_id, date_str)
        )
        conn.commit()
    finally:
        conn.close()


def get_monthly_attendance(employee_id, year_month):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM attendance WHERE employee_id = %s AND date LIKE %s ORDER BY date",
            (employee_id, f"{year_month}%")
        )
        return cur.fetchall()
    finally:
        conn.close()


def get_temp_state(line_user_id):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT state, data FROM temp_state WHERE line_user_id = %s", (line_user_id,))
        row = cur.fetchone()
        return (row['state'], row['data']) if row else (None, None)
    finally:
        conn.close()


def set_temp_state(line_user_id, state, data=''):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO temp_state (line_user_id, state, data) VALUES (%s, %s, %s)
               ON CONFLICT (line_user_id) DO UPDATE SET state = %s, data = %s""",
            (line_user_id, state, data, state, data)
        )
        conn.commit()
    finally:
        conn.close()


def clear_temp_state(line_user_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM temp_state WHERE line_user_id = %s", (line_user_id,))
        conn.commit()
    finally:
        conn.close()


def deactivate_employee(name):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE employees SET is_active = FALSE WHERE name = %s", (name,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


init_db()
