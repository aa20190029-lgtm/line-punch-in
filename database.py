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
        # 建立基本資料表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                line_user_id TEXT UNIQUE,
                name TEXT NOT NULL,
                hourly_wage INTEGER DEFAULT 200,
                shift_start TEXT DEFAULT '10:30',
                shift_end TEXT DEFAULT '14:30',
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
                overtime_minutes INTEGER DEFAULT 0
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

        # 初始設定值
        for key, value in [
            ('boss_line_id', ''),
            ('gps_enabled', '0'),
            ('store_lat', ''),
            ('store_lng', ''),
            ('gps_radius_meters', '100'),
            ('late_grace_minutes', '5'),
        ]:
            cur.execute(
                "INSERT INTO config (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (key, value)
            )

        # 資料庫升級：新增欄位
        cur.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS salary_type TEXT DEFAULT 'hourly'")
        cur.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS monthly_salary INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS hire_date TEXT DEFAULT ''")
        cur.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'employee'")

        # 允許 line_user_id 為 NULL（老闆建立尚未綁定的員工）
        cur.execute("ALTER TABLE employees ALTER COLUMN line_user_id DROP NOT NULL")

        # 請假記錄表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS leave_records (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                date TEXT NOT NULL,
                leave_type TEXT DEFAULT 'personal',
                created_at TEXT DEFAULT '',
                UNIQUE (employee_id, date)
            )
        """)
        cur.execute("ALTER TABLE leave_records ALTER COLUMN leave_type SET DEFAULT 'personal'")

        # 國定假日加班費記錄表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS holiday_bonuses (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                date TEXT NOT NULL,
                bonus_amount INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT '',
                UNIQUE (employee_id, date)
            )
        """)

        # 出勤表：新增班次欄位
        cur.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS shift_number INTEGER DEFAULT 1")
        cur.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS is_manual BOOLEAN DEFAULT FALSE")

        # 修改唯一約束：改為 (employee_id, date, shift_number)
        cur.execute("""
            DO $$
            BEGIN
                ALTER TABLE attendance DROP CONSTRAINT IF EXISTS attendance_employee_id_date_key;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'attendance_employee_id_date_shift_key'
                ) THEN
                    ALTER TABLE attendance ADD CONSTRAINT attendance_employee_id_date_shift_key
                    UNIQUE (employee_id, date, shift_number);
                END IF;
            END $$;
        """)

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
        cur.execute(
            "SELECT * FROM employees WHERE line_user_id = %s AND is_active = TRUE",
            (line_user_id,)
        )
        return cur.fetchone()
    finally:
        conn.close()


def get_employee_by_name(name):
    """取得已綁定或未綁定的員工（is_active = TRUE）"""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM employees WHERE name = %s AND is_active = TRUE", (name,))
        return cur.fetchone()
    finally:
        conn.close()


def get_unbound_employee_by_name(name):
    """取得尚未綁定 LINE 的員工（老闆建立但員工還未登記）"""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM employees WHERE name = %s AND is_active = TRUE AND line_user_id IS NULL",
            (name,)
        )
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


def add_employee_profile(name, hire_date_iso, salary_type, salary_amount):
    """老闆建立員工資料（line_user_id=NULL，等員工自行綁定）"""
    import pytz
    from datetime import datetime
    created_at = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        cur = conn.cursor()
        if salary_type == 'monthly':
            cur.execute(
                """INSERT INTO employees
                   (line_user_id, name, salary_type, monthly_salary, hourly_wage, hire_date, shift_start, shift_end, created_at)
                   VALUES (NULL, %s, 'monthly', %s, 0, %s, '10:30', '14:30', %s)""",
                (name, salary_amount, hire_date_iso or '', created_at)
            )
        else:
            cur.execute(
                """INSERT INTO employees
                   (line_user_id, name, salary_type, hourly_wage, monthly_salary, hire_date, shift_start, shift_end, created_at)
                   VALUES (NULL, %s, 'hourly', %s, 0, %s, '10:30', '14:30', %s)""",
                (name, salary_amount, hire_date_iso or '', created_at)
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def bind_employee_line_id(name, line_user_id):
    """員工自行登記：將 LINE ID 綁定到老闆建立的未綁定員工資料"""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE employees SET line_user_id = %s
               WHERE name = %s AND is_active = TRUE AND line_user_id IS NULL""",
            (line_user_id, name)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_employee_salary(name, salary_type, hourly_wage=None, monthly_salary=None):
    conn = get_db()
    try:
        cur = conn.cursor()
        if salary_type == 'monthly':
            cur.execute(
                "UPDATE employees SET salary_type = %s, monthly_salary = %s WHERE name = %s AND is_active = TRUE",
                ('monthly', monthly_salary or 0, name)
            )
        else:
            cur.execute(
                "UPDATE employees SET salary_type = %s, hourly_wage = %s WHERE name = %s AND is_active = TRUE",
                ('hourly', hourly_wage or 200, name)
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_employee_hire_date(name, hire_date_iso):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE employees SET hire_date = %s WHERE name = %s AND is_active = TRUE",
            (hire_date_iso, name)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_today_shift_attendance(employee_id, date_str, shift_number):
    """取得特定班次的打卡記錄"""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM attendance WHERE employee_id = %s AND date = %s AND shift_number = %s",
            (employee_id, date_str, shift_number)
        )
        return cur.fetchone()
    finally:
        conn.close()


def get_today_all_shifts(employee_id, date_str):
    """取得今日所有班次的打卡記錄（列表）"""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM attendance WHERE employee_id = %s AND date = %s ORDER BY shift_number",
            (employee_id, date_str)
        )
        return cur.fetchall()
    finally:
        conn.close()


def punch_in(employee_id, date_str, time_str, late_minutes, shift_number=1):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO attendance (employee_id, date, punch_in, late_minutes, shift_number)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT ON CONSTRAINT attendance_employee_id_date_shift_key
               DO UPDATE SET punch_in = %s, late_minutes = %s""",
            (employee_id, date_str, time_str, late_minutes, shift_number, time_str, late_minutes)
        )
        conn.commit()
    finally:
        conn.close()


def punch_out(employee_id, date_str, time_str, overtime_minutes, shift_number=1):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE attendance SET punch_out = %s, overtime_minutes = %s
               WHERE employee_id = %s AND date = %s AND shift_number = %s""",
            (time_str, overtime_minutes, employee_id, date_str, shift_number)
        )
        conn.commit()
    finally:
        conn.close()


def add_manual_punch(employee_id, date_str, shift_number, punch_in_time, punch_out_time, late_minutes, overtime_minutes):
    """老闆補打卡"""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO attendance
               (employee_id, date, shift_number, punch_in, punch_out, late_minutes, overtime_minutes, is_manual)
               VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
               ON CONFLICT ON CONSTRAINT attendance_employee_id_date_shift_key
               DO UPDATE SET punch_in = %s, punch_out = %s, late_minutes = %s, overtime_minutes = %s, is_manual = TRUE""",
            (employee_id, date_str, shift_number, punch_in_time, punch_out_time,
             late_minutes, overtime_minutes,
             punch_in_time, punch_out_time, late_minutes, overtime_minutes)
        )
        conn.commit()
    finally:
        conn.close()


def get_monthly_attendance(employee_id, year_month):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM attendance WHERE employee_id = %s AND date LIKE %s ORDER BY date, shift_number",
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


def add_leave_record(employee_id, date_str, leave_type='personal'):
    import pytz
    from datetime import datetime
    created_at = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO leave_records (employee_id, date, leave_type, created_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (employee_id, date) DO NOTHING""",
            (employee_id, date_str, leave_type, created_at)
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_monthly_leave_records(employee_id, year_month):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM leave_records WHERE employee_id = %s AND date LIKE %s ORDER BY date",
            (employee_id, f"{year_month}%")
        )
        return cur.fetchall()
    finally:
        conn.close()


def add_holiday_bonus(employee_id, date_str, bonus_amount):
    """新增國定假日加班費記錄"""
    import pytz
    from datetime import datetime
    created_at = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO holiday_bonuses (employee_id, date, bonus_amount, created_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (employee_id, date) DO NOTHING""",
            (employee_id, date_str, bonus_amount, created_at)
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_monthly_holiday_bonuses(employee_id, year_month):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM holiday_bonuses WHERE employee_id = %s AND date LIKE %s ORDER BY date",
            (employee_id, f"{year_month}%")
        )
        return cur.fetchall()
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
