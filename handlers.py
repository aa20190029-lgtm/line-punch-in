import math
import pytz
from datetime import datetime, date as date_cls

from database import (
    get_employee_by_line_id, get_employee_by_name, get_unbound_employee_by_name,
    get_all_employees, add_employee_profile, bind_employee_line_id,
    get_today_shift_attendance, get_today_all_shifts,
    punch_in, punch_out, add_manual_punch,
    get_monthly_attendance, get_config, set_config,
    get_temp_state, set_temp_state, clear_temp_state, deactivate_employee,
    update_employee_salary, update_employee_hire_date,
    add_leave_record, get_monthly_leave_records,
    add_holiday_bonus, get_monthly_holiday_bonuses,
)
from salary import (
    calc_overtime_pay, calc_late_deduction, calc_monthly_summary,
    roc_to_iso, HOURS_PER_SHIFT, LEAVE_TYPE_LABELS,
)
from line_config import link_user_to_boss_menu, link_user_to_employee_menu

TZ = pytz.timezone('Asia/Taipei')

# 固定班次設定
SHIFTS = {
    1: {'start': '10:30', 'end': '14:30', 'window_start': 600,  'window_end': 900},   # 10:00-15:00
    2: {'start': '16:30', 'end': '20:30', 'window_start': 960,  'window_end': 1260},  # 16:00-21:00
}

EMPLOYEE_HELP = """📋 打卡說明
上班：點「上班打卡」
下班：點「下班打卡」
第一班：10:30 上班 / 14:30 下班
第二班：16:30 上班 / 20:30 下班

查詢：點「查本月薪資」或「查打卡記錄」
首次使用：點「登記」輸入姓名"""

BOSS_HELP = """👔 管理說明
員工管理：新增/查詢/薪資/刪除
補打卡：幫員工補上漏打的紀錄
薪資報表：本月全員薪資總覽

GPS設定（文字輸入）：
GPS設定 → GPS開啟 / GPS關閉"""


def now_tw():
    return datetime.now(TZ)


def today_str():
    return now_tw().strftime('%Y-%m-%d')


def time_str():
    return now_tw().strftime('%H:%M')


def month_str():
    return now_tw().strftime('%Y-%m')


def is_boss(line_user_id):
    boss_id = get_config('boss_line_id')
    return bool(boss_id) and boss_id == line_user_id


def get_shift_by_time(t):
    """根據時間判斷班次，回傳 (shift_num, start, end) 或 (None, None, None)"""
    h, m = map(int, t.split(':'))
    total = h * 60 + m
    for num, info in SHIFTS.items():
        if info['window_start'] <= total <= info['window_end']:
            return num, info['start'], info['end']
    return None, None, None


def parse_time_input(text):
    """接受 HHMM 或 HH:MM 格式，回傳 HH:MM 或 None"""
    text = text.strip().replace(':', '')
    if len(text) == 4 and text.isdigit():
        h, m = int(text[:2]), int(text[2:])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f'{h:02d}:{m:02d}'
    return None


def calc_late(punch_time, shift_start, grace=5):
    ph, pm = map(int, punch_time.split(':'))
    sh, sm = map(int, shift_start.split(':'))
    late = (ph * 60 + pm) - (sh * 60 + sm + grace)
    return max(0, late)


def calc_overtime(punch_out_time, shift_end):
    oh, om = map(int, punch_out_time.split(':'))
    sh, sm = map(int, shift_end.split(':'))
    ot = (oh * 60 + om) - (sh * 60 + sm)
    return max(0, ot)


def worked_hours(punch_in_t, punch_out_t):
    ih, im = map(int, punch_in_t.split(':'))
    oh, om = map(int, punch_out_t.split(':'))
    return ((oh * 60 + om) - (ih * 60 + im)) / 60


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def qr(text, buttons):
    return {'text': text, 'quick_replies': buttons}


# ──────────────────────────────────────────
#  主入口
# ──────────────────────────────────────────

def handle_message(line_user_id, text):
    text = text.strip()

    state, data = get_temp_state(line_user_id)
    if state:
        return handle_state(line_user_id, text, state, data)

    # 設為老闆
    if text == '設為老闆':
        boss_id = get_config('boss_line_id')
        if boss_id and boss_id != line_user_id:
            return '❌ 老闆帳號已設定。\n如需更換請聯絡目前老闆。'
        set_config('boss_line_id', line_user_id)
        link_user_to_boss_menu(line_user_id)
        return qr('✅ 已設為老闆帳號！\n點「說明」查看所有功能。', ['說明'])

    # 說明
    if text in ['說明', 'help', '？', '?', '幫助']:
        if is_boss(line_user_id):
            return BOSS_HELP
        emp = get_employee_by_line_id(line_user_id)
        if emp:
            return EMPLOYEE_HELP
        return qr('歡迎使用非晉餐廚打卡系統！\n\n請點「登記」輸入姓名完成綁定。', ['登記'])

    # ── 員工打卡 ──
    if text in ['上班打卡', '打卡上班']:
        return handle_punch_in(line_user_id)

    if text in ['下班打卡', '打卡下班']:
        return handle_punch_out(line_user_id)

    if text in ['查本月薪資', '我的本月', '本月出勤']:
        return handle_my_month(line_user_id)

    if text in ['查打卡記錄', '我的今日', '今日紀錄']:
        return handle_my_today(line_user_id)

    # 登記（綁定 LINE ID）
    if text in ['登記', '加入', '我要登記']:
        emp = get_employee_by_line_id(line_user_id)
        if emp:
            return qr(f'✅ 你已登記為「{emp["name"]}」', ['上班打卡', '說明'])
        set_temp_state(line_user_id, 'register_name')
        return '📝 請輸入你的姓名（中文）：'

    # ── 老闆功能 ──
    if not is_boss(line_user_id):
        emp = get_employee_by_line_id(line_user_id)
        if not emp:
            return qr('你尚未登記。\n請點「登記」輸入姓名。', ['登記'])
        return None

    if text == '員工管理':
        return qr('👥 員工管理\n請選擇操作：', ['查詢員工', '新增員工', '設定薪資', '請假登記', '國定假日加班', '刪除員工'])

    if text in ['查詢員工', '員工列表']:
        return handle_employee_list()

    if text == '新增員工':
        set_temp_state(line_user_id, 'boss_add_name')
        return '📝 新增員工\n\n請輸入員工姓名（中文）：'

    if text in ['設定薪資', '薪資設定']:
        return handle_show_salary_select(line_user_id)

    if text == '請假登記':
        return handle_leave_register_start(line_user_id)

    if text == '國定假日加班':
        return handle_holiday_bonus_start(line_user_id)

    if text == '刪除員工':
        return handle_show_delete_select(line_user_id)

    if text in ['補打卡', '手動補打']:
        return handle_manual_punch_start(line_user_id)

    if text in ['薪資報表', '月報表']:
        return handle_monthly_report()

    if text in ['今日出勤']:
        return handle_today_attendance()

    if text.startswith('查詢 ') or text.startswith('查詢　'):
        name = text.replace('查詢', '').strip()
        return handle_query_employee(name)

    if text == 'GPS設定':
        return handle_gps_setup_start(line_user_id)

    if text == 'GPS開啟':
        return handle_gps_toggle(True)

    if text == 'GPS關閉':
        return handle_gps_toggle(False)

    if text == 'GPS狀態':
        return handle_gps_status()

    return None


# ──────────────────────────────────────────
#  狀態機
# ──────────────────────────────────────────

def handle_state(line_user_id, text, state, data):

    # GPS 等待位置
    if state == 'pending_punch_in':
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消打卡。'
        return qr('請分享你的位置以完成上班打卡\n或輸入「取消」放棄', ['📍分享位置', '取消'])

    if state == 'pending_punch_out':
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消打卡。'
        return qr('請分享你的位置以完成下班打卡\n或輸入「取消」放棄', ['📍分享位置', '取消'])

    if state == 'set_store_gps':
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消GPS設定。'
        # 接受手動輸入座標，格式：緯度,經度（例：25.0478,121.5319）
        import re
        coord_match = re.match(r'^(-?\d+\.?\d*)\s*[,，]\s*(-?\d+\.?\d*)$', text.strip())
        if coord_match:
            lat = float(coord_match.group(1))
            lng = float(coord_match.group(2))
            set_temp_state(line_user_id, 'set_store_gps_radius', f'{lat},{lng}')
            return f'✅ 已收到店家座標\n{lat:.6f}, {lng:.6f}\n\n請輸入打卡範圍（公尺，建議100）：'
        return qr('請分享店家位置，或直接輸入座標\n例：25.0478,121.5319', ['📍分享位置', '取消'])

    # GPS 半徑設定
    if state == 'set_store_gps_radius':
        try:
            radius = int(text.strip())
            if radius <= 0:
                raise ValueError
        except ValueError:
            clear_temp_state(line_user_id)
            return '❌ 請輸入有效公尺數（如：100）。\n發送「GPS設定」重試。'
        lat, lng = map(float, data.split(',', 1))
        set_config('store_lat', str(lat))
        set_config('store_lng', str(lng))
        set_config('gps_radius_meters', str(radius))
        clear_temp_state(line_user_id)
        return f'✅ GPS設定完成\n位置：{lat:.6f}, {lng:.6f}\n範圍：{radius} 公尺\n\n發送「GPS開啟」啟用。'

    # 員工登記（綁定姓名）
    if state == 'register_name':
        name = text.strip()
        if not name or len(name) > 10:
            clear_temp_state(line_user_id)
            return '❌ 請輸入正確姓名（10字以內）。\n點「登記」重試。'
        unbound = get_unbound_employee_by_name(name)
        if unbound:
            ok = bind_employee_line_id(name, line_user_id)
            clear_temp_state(line_user_id)
            if ok:
                link_user_to_employee_menu(line_user_id)
                return qr(f'✅ 登記成功！歡迎，{name}！\n\n可以開始打卡了。', ['上班打卡', '說明'])
        # 找不到未綁定的員工
        clear_temp_state(line_user_id)
        return ('❌ 找不到你的資料。\n\n'
                '請確認姓名是否正確，\n或聯絡老闆確認帳號是否已建立。')

    # ── 老闆：新增員工 ──
    if state == 'boss_add_name':
        name = text.strip()
        if not name or len(name) > 10:
            clear_temp_state(line_user_id)
            return '❌ 請輸入正確姓名（10字以內）。'
        if get_employee_by_name(name):
            clear_temp_state(line_user_id)
            return f'❌ 「{name}」已存在。\n點「新增員工」重試。'
        set_temp_state(line_user_id, 'boss_add_hire_date', name)
        return f'姓名：{name}\n\n請輸入入職日（民國年，如：1150620）\n不需要請輸入「略過」：'

    if state == 'boss_add_hire_date':
        name = data
        if text.strip() in ['略過', '跳過', '不用', '無']:
            hire_date_iso = ''
        else:
            hire_date_iso = roc_to_iso(text.strip()) or ''
            if not hire_date_iso:
                clear_temp_state(line_user_id)
                return '❌ 日期格式有誤（如：1150620）。\n點「新增員工」重試。'
        set_temp_state(line_user_id, 'boss_add_salary_type', f'{name}|{hire_date_iso}')
        hire_show = hire_date_iso if hire_date_iso else '未設定'
        return qr(f'入職日：{hire_show}\n\n請選擇薪資類型：', ['月薪', '時薪'])

    if state == 'boss_add_salary_type':
        parts = data.split('|', 1)
        name, hire_date_iso = parts[0], parts[1] if len(parts) > 1 else ''
        if text not in ['月薪', '時薪']:
            clear_temp_state(line_user_id)
            return '❌ 請選擇「月薪」或「時薪」。'
        salary_type = 'monthly' if text == '月薪' else 'hourly'
        set_temp_state(line_user_id, 'boss_add_salary_amount', f'{name}|{hire_date_iso}|{salary_type}')
        hint = '月薪金額（如：38000）' if text == '月薪' else '時薪金額（如：200）'
        return f'請輸入{hint}：'

    if state == 'boss_add_salary_amount':
        parts = data.split('|', 2)
        name, hire_date_iso, salary_type = parts[0], parts[1], parts[2]
        try:
            amount = int(text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            clear_temp_state(line_user_id)
            return '❌ 請輸入有效金額（如：38000）。'
        ok = add_employee_profile(name, hire_date_iso or None, salary_type, amount)
        clear_temp_state(line_user_id)
        if not ok:
            return '❌ 新增失敗，請重試。'
        label = '月薪' if salary_type == 'monthly' else '時薪'
        hire_msg = f'\n入職日：{hire_date_iso}' if hire_date_iso else ''
        return (f'✅ 員工「{name}」已建立\n'
                f'{label}：{amount:,} 元{hire_msg}\n\n'
                f'請通知 {name} 加入 LINE OA，\n'
                f'點「登記」輸入姓名「{name}」即可完成綁定。')

    # ── 老闆：選員工設定薪資 ──
    if state == 'boss_salary_select':
        name = text.strip()
        clear_temp_state(line_user_id)
        return handle_set_salary_start(line_user_id, name)

    # ── 老闆：請假登記選員工 ──
    if state == 'boss_leave_select':
        name = text.strip()
        emp = get_employee_by_name(name)
        if not emp:
            clear_temp_state(line_user_id)
            return f'❌ 找不到員工「{name}」'
        set_temp_state(line_user_id, 'boss_leave_type', str(emp['id']))
        return qr(f'員工：{name}\n\n請選擇假別：', ['事假', '病假', '喪假', '婚假'])

    # ── 老闆：請假登記選假別 ──
    if state == 'boss_leave_type':
        emp_id = data
        leave_map = {'事假': 'personal', '病假': 'sick', '喪假': 'funeral', '婚假': 'wedding'}
        if text.strip() not in leave_map:
            clear_temp_state(line_user_id)
            return '❌ 請選擇假別（事假／病假／喪假／婚假）。'
        leave_type = leave_map[text.strip()]
        set_temp_state(line_user_id, 'boss_leave_date', f'{emp_id}|{leave_type}')
        return '請輸入請假日期（民國年，如：1140608）：'

    # ── 老闆：請假登記輸入日期 ──
    if state == 'boss_leave_date':
        parts = data.split('|', 1)
        emp_id = int(parts[0])
        leave_type = parts[1] if len(parts) > 1 else 'personal'
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消請假登記。'
        date_iso = roc_to_iso(text.strip())
        if not date_iso:
            clear_temp_state(line_user_id)
            return '❌ 日期格式有誤（如：1140608）。\n請重新點「請假登記」。'
        ok = add_leave_record(emp_id, date_iso, leave_type)
        clear_temp_state(line_user_id)
        leave_label = LEAVE_TYPE_LABELS.get(leave_type, '假')
        deduct_notes = {
            'personal': '薪資報表將扣除全日薪資（月薪÷30）。',
            'sick':     '薪資報表將扣除半日薪資（月薪÷30÷2）。',
            'funeral':  '工資照給，不扣薪資。',
            'wedding':  '工資照給，不扣薪資。',
        }
        note = deduct_notes.get(leave_type, '')
        if ok:
            return f'✅ {leave_label}登記完成\n日期：{date_iso}\n{note}'
        return '⚠️ 該日期已登記過請假，無需重複登記。'

    # ── 老闆：國定假日加班費選員工 ──
    if state == 'boss_holiday_select':
        name = text.strip()
        emp = get_employee_by_name(name)
        if not emp:
            clear_temp_state(line_user_id)
            return f'❌ 找不到員工「{name}」'
        salary_type = emp.get('salary_type') or 'hourly'
        wage = emp.get('monthly_salary') if salary_type == 'monthly' else (emp.get('hourly_wage') or 200)
        set_temp_state(line_user_id, 'boss_holiday_date', f'{emp["id"]}|{salary_type}|{wage}')
        return f'員工：{name}\n\n請輸入國定假日日期（民國年，如：1140101）：'

    # ── 老闆：國定假日加班費輸入日期 ──
    if state == 'boss_holiday_date':
        parts = data.split('|', 2)
        emp_id, salary_type, wage = int(parts[0]), parts[1], int(parts[2])
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消。'
        date_iso = roc_to_iso(text.strip())
        if not date_iso:
            clear_temp_state(line_user_id)
            return '❌ 日期格式有誤（如：1140101）。\n請重新點「國定假日加班」。'
        if salary_type == 'monthly':
            bonus = round(wage / 30)
            ok = add_holiday_bonus(emp_id, date_iso, bonus)
            clear_temp_state(line_user_id)
            if ok:
                return f'✅ 國定假日加班費登記完成\n日期：{date_iso}\n加給：+{bonus:,} 元\n（月薪{wage:,}÷30）'
            return '⚠️ 該日期已登記過，無需重複登記。'
        else:
            ym = date_iso[:7]
            day_records = [r for r in get_monthly_attendance(emp_id, ym)
                           if r['date'] == date_iso and r['punch_in']]
            if day_records:
                total_shifts = len(day_records)
                bonus = round(wage * HOURS_PER_SHIFT * total_shifts)
                ok = add_holiday_bonus(emp_id, date_iso, bonus)
                clear_temp_state(line_user_id)
                if ok:
                    return (f'✅ 國定假日加班費登記完成\n日期：{date_iso}\n'
                            f'加給：+{bonus:,} 元\n'
                            f'（時薪{wage}×{HOURS_PER_SHIFT}h×{total_shifts}班）')
                return '⚠️ 該日期已登記過，無需重複登記。'
            else:
                set_temp_state(line_user_id, 'boss_holiday_hours', f'{emp_id}|{date_iso}|{wage}')
                return f'⚠️ 找不到 {date_iso} 的打卡記錄\n\n請輸入該日出勤時數（如：4）：'

    # ── 老闆：國定假日加班費手動輸入時數 ──
    if state == 'boss_holiday_hours':
        parts = data.split('|', 2)
        emp_id, date_iso, wage = int(parts[0]), parts[1], int(parts[2])
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消。'
        try:
            hours = float(text.strip())
            if hours <= 0:
                raise ValueError
        except ValueError:
            clear_temp_state(line_user_id)
            return '❌ 請輸入有效時數（如：4）。'
        bonus = round(wage * hours)
        ok = add_holiday_bonus(emp_id, date_iso, bonus)
        clear_temp_state(line_user_id)
        if ok:
            return f'✅ 國定假日加班費登記完成\n日期：{date_iso}\n加給：+{bonus:,} 元\n（時薪{wage}×{hours}h）'
        return '⚠️ 該日期已登記過，無需重複登記。'

    # ── 老闆：選員工刪除 ──
    if state == 'boss_delete_select':
        name = text.strip()
        clear_temp_state(line_user_id)
        return handle_delete_employee(name)

    # ── 老闆：設定薪資流程 ──
    if state == 'set_salary_type':
        name = data
        if text == '月薪':
            set_temp_state(line_user_id, 'set_salary_amount', f'{name}|monthly')
            return f'請輸入 {name} 的月薪金額（如：38000）：'
        elif text == '時薪':
            set_temp_state(line_user_id, 'set_salary_amount', f'{name}|hourly')
            return f'請輸入 {name} 的時薪金額（如：200）：'
        else:
            clear_temp_state(line_user_id)
            return '❌ 請輸入「月薪」或「時薪」。'

    if state == 'set_salary_amount':
        parts = data.split('|', 1)
        name, salary_type = parts[0], parts[1]
        try:
            amount = int(text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            clear_temp_state(line_user_id)
            return '❌ 請輸入有效金額（如：38000）。'
        if salary_type == 'monthly':
            update_employee_salary(name, 'monthly', monthly_salary=amount)
        else:
            update_employee_salary(name, 'hourly', hourly_wage=amount)
        clear_temp_state(line_user_id)
        label = '月薪' if salary_type == 'monthly' else '時薪'
        return f'✅ {name} 薪資已更新\n{label}：{amount:,} 元'

    # ── 老闆：補打卡流程 ──
    if state == 'boss_manual_name':
        name = text.strip()
        emp = get_employee_by_name(name)
        if not emp:
            clear_temp_state(line_user_id)
            return f'❌ 找不到員工「{name}」。\n點「補打卡」重試。'
        set_temp_state(line_user_id, 'boss_manual_date', str(emp['id']))
        return f'員工：{name}\n\n請輸入日期（MMDD，如：0608）：'

    if state == 'boss_manual_date':
        emp_id = int(data)
        d_input = text.strip()
        if len(d_input) != 4 or not d_input.isdigit():
            clear_temp_state(line_user_id)
            return '❌ 請輸入4位數日期（如：0608）。'
        try:
            year = now_tw().year
            month, day = int(d_input[:2]), int(d_input[2:])
            d = date_cls(year, month, day)
            date_iso = d.isoformat()
        except ValueError:
            clear_temp_state(line_user_id)
            return '❌ 日期無效，請重新輸入（如：0608）。'
        set_temp_state(line_user_id, 'boss_manual_shift', f'{emp_id}|{date_iso}')
        return qr(f'日期：{date_iso}\n\n請選擇班次：',
                  ['第一班（10:30-14:30）', '第二班（16:30-20:30）'])

    if state == 'boss_manual_shift':
        parts = data.split('|', 1)
        emp_id, date_iso = int(parts[0]), parts[1]
        if '第一班' in text:
            shift_num, s_start, s_end = 1, '10:30', '14:30'
        elif '第二班' in text:
            shift_num, s_start, s_end = 2, '16:30', '20:30'
        else:
            clear_temp_state(line_user_id)
            return '❌ 請選擇班次。'
        set_temp_state(line_user_id, 'boss_manual_in', f'{emp_id}|{date_iso}|{shift_num}|{s_start}|{s_end}')
        return f'第{shift_num}班（{s_start}-{s_end}）\n\n請輸入上班時間（如：1025 或 10:25）：'

    if state == 'boss_manual_in':
        parts = data.split('|', 4)
        emp_id, date_iso = int(parts[0]), parts[1]
        shift_num, s_start, s_end = int(parts[2]), parts[3], parts[4]
        pin_time = parse_time_input(text)
        if not pin_time:
            clear_temp_state(line_user_id)
            return '❌ 時間格式有誤（如：1025）。'
        set_temp_state(line_user_id, 'boss_manual_out',
                       f'{emp_id}|{date_iso}|{shift_num}|{s_start}|{s_end}|{pin_time}')
        return f'上班：{pin_time}\n\n請輸入下班時間（如：1430）\n若只補上班打卡請輸入「略過」：'

    if state == 'boss_manual_out':
        parts = data.split('|', 5)
        emp_id, date_iso = int(parts[0]), parts[1]
        shift_num, s_start, s_end, pin_time = int(parts[2]), parts[3], parts[4], parts[5]

        pout_time = None
        if text.strip() not in ['略過', '跳過', '不用']:
            pout_time = parse_time_input(text)
            if not pout_time:
                clear_temp_state(line_user_id)
                return '❌ 時間格式有誤（如：1430）。'

        grace = int(get_config('late_grace_minutes') or 5)
        late = calc_late(pin_time, s_start, grace)
        ot = calc_overtime(pout_time, s_end) if pout_time else 0
        add_manual_punch(emp_id, date_iso, shift_num, pin_time, pout_time, late, ot)
        clear_temp_state(line_user_id)

        msg = (f'✅ 補打卡完成 📝\n'
               f'日期：{date_iso}　第{shift_num}班\n'
               f'上班：{pin_time}')
        if late > 0:
            msg += f' ⚠️遲{late}分'
        if pout_time:
            msg += f'\n下班：{pout_time}'
            if ot > 0:
                msg += f' 加班{ot}分'
        return msg

    clear_temp_state(line_user_id)
    return None


# ──────────────────────────────────────────
#  GPS 位置處理
# ──────────────────────────────────────────

def handle_location(line_user_id, lat, lng):
    state, data = get_temp_state(line_user_id)

    if is_boss(line_user_id) and state == 'set_store_gps':
        set_temp_state(line_user_id, 'set_store_gps_radius', f'{lat},{lng}')
        return (f'✅ 已收到店家位置\n{lat:.6f}, {lng:.6f}\n\n'
                f'請輸入打卡範圍（公尺，建議100）：')

    if state in ('pending_punch_in', 'pending_punch_out'):
        store_lat_str = get_config('store_lat') or ''
        store_lng_str = get_config('store_lng') or ''
        if not store_lat_str or not store_lng_str:
            clear_temp_state(line_user_id)
            return '❌ 店家位置尚未設定，請聯絡老闆。'

        dist = haversine_distance(lat, lng, float(store_lat_str), float(store_lng_str))
        radius = float(get_config('gps_radius_meters') or 100)

        if dist > radius:
            clear_temp_state(line_user_id)
            return (f'❌ 位置不在打卡範圍內\n'
                    f'你距店家 {dist:.0f} 公尺\n'
                    f'需在 {radius:.0f} 公尺以內')

        shift_num = int(data) if data and data.isdigit() else None
        clear_temp_state(line_user_id)
        if state == 'pending_punch_in':
            return _do_punch_in(line_user_id, shift_num)
        else:
            return _do_punch_out(line_user_id, shift_num)

    return None


# ──────────────────────────────────────────
#  打卡邏輯
# ──────────────────────────────────────────

def handle_punch_in(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return qr('❌ 你尚未登記。請點「登記」。', ['登記'])

    t = time_str()
    shift_num, s_start, s_end = get_shift_by_time(t)
    if shift_num is None:
        return ('❌ 目前不在班表時間內\n\n'
                '第一班上班：10:00–15:00\n'
                '第二班上班：16:00–21:00')

    today = today_str()
    record = get_today_shift_attendance(emp['id'], today, shift_num)
    if record and record['punch_in']:
        return f'⚠️ 第{shift_num}班已打過上班卡！\n時間：{record["punch_in"]}'

    gps_enabled = get_config('gps_enabled') == '1'
    if gps_enabled:
        set_temp_state(line_user_id, 'pending_punch_in', str(shift_num))
        return qr(f'📍 GPS打卡\n請分享你的位置完成第{shift_num}班上班打卡：', ['📍分享位置'])

    return _do_punch_in(line_user_id, shift_num)


def handle_punch_out(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return qr('❌ 你尚未登記。請點「登記」。', ['登記'])

    t = time_str()
    shift_num, s_start, s_end = get_shift_by_time(t)
    if shift_num is None:
        return ('❌ 目前不在班表時間內\n\n'
                '第一班下班：10:00–15:00\n'
                '第二班下班：16:00–21:00')

    today = today_str()
    record = get_today_shift_attendance(emp['id'], today, shift_num)
    if not record or not record['punch_in']:
        return f'❌ 第{shift_num}班還沒打上班卡！\n請先點「上班打卡」。'
    if record['punch_out']:
        return f'⚠️ 第{shift_num}班已打過下班卡！\n時間：{record["punch_out"]}'

    gps_enabled = get_config('gps_enabled') == '1'
    if gps_enabled:
        set_temp_state(line_user_id, 'pending_punch_out', str(shift_num))
        return qr(f'📍 GPS打卡\n請分享你的位置完成第{shift_num}班下班打卡：', ['📍分享位置'])

    return _do_punch_out(line_user_id, shift_num)


def _do_punch_in(line_user_id, shift_num=None):
    emp = get_employee_by_line_id(line_user_id)
    t = time_str()
    if shift_num is None:
        shift_num, _, _ = get_shift_by_time(t)
    if shift_num is None:
        return '❌ 目前不在班表時間內。'

    shift = SHIFTS[shift_num]
    grace = int(get_config('late_grace_minutes') or 5)
    late = calc_late(t, shift['start'], grace)
    punch_in(emp['id'], today_str(), t, late, shift_num)

    msg = (f'✅ 上班打卡成功\n'
           f'{emp["name"]}　第{shift_num}班\n'
           f'時間：{t}　（班表 {shift["start"]}）')
    if late > 0:
        msg += f'\n⚠️ 遲到 {late} 分鐘'
    else:
        msg += '\n準時！'
    return qr(msg, ['下班打卡', '查打卡記錄'])


def _do_punch_out(line_user_id, shift_num=None):
    emp = get_employee_by_line_id(line_user_id)
    t = time_str()
    if shift_num is None:
        shift_num, _, _ = get_shift_by_time(t)
    if shift_num is None:
        return '❌ 目前不在班表時間內。'

    shift = SHIFTS[shift_num]
    today = today_str()
    record = get_today_shift_attendance(emp['id'], today, shift_num)

    ot = calc_overtime(t, shift['end'])
    punch_out(emp['id'], today, t, ot, shift_num)
    worked = worked_hours(record['punch_in'], t) if record else 0

    salary_type = emp.get('salary_type') or 'hourly'
    if salary_type == 'monthly':
        hourly_rate = (emp.get('monthly_salary') or 0) / 240
    else:
        hourly_rate = emp.get('hourly_wage') or 200

    msg = (f'✅ 下班打卡成功\n'
           f'{emp["name"]}　第{shift_num}班\n'
           f'時間：{t}　工作 {worked:.1f} 小時')
    if ot > 0:
        ot_pay = calc_overtime_pay(hourly_rate, ot)
        msg += f'\n加班 {ot} 分鐘（+{ot_pay} 元）'
    if record and record.get('late_minutes', 0) and record['late_minutes'] > 0:
        late_deduct = calc_late_deduction(hourly_rate, record['late_minutes'])
        msg += f'\n遲到 {record["late_minutes"]} 分鐘（-{late_deduct} 元）'
    return qr(msg, ['查打卡記錄', '查本月薪資'])


# ──────────────────────────────────────────
#  員工查詢
# ──────────────────────────────────────────

def handle_my_today(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return '❌ 你尚未登記。'

    today = today_str()
    records = get_today_all_shifts(emp['id'], today)

    if not records:
        return qr(f'📅 {today}\n今日尚未打卡。', ['上班打卡'])

    msg = f'📅 {emp["name"]} {today}\n'
    for r in records:
        sn = r.get('shift_number') or 1
        shift = SHIFTS.get(sn, SHIFTS[1])
        manual_tag = ' 📝補' if r.get('is_manual') else ''
        msg += f'\n第{sn}班（{shift["start"]}-{shift["end"]}）{manual_tag}'
        if r['punch_in']:
            late_tag = f' ⚠️遲{r["late_minutes"]}分' if r.get('late_minutes', 0) and r['late_minutes'] > 0 else ''
            msg += f'\n  上班：{r["punch_in"]}{late_tag}'
        if r['punch_out']:
            w = worked_hours(r['punch_in'], r['punch_out'])
            ot_tag = f' +加班{r["overtime_minutes"]}分' if r.get('overtime_minutes', 0) and r['overtime_minutes'] > 0 else ''
            msg += f'\n  下班：{r["punch_out"]}（{w:.1f}h）{ot_tag}'
        else:
            msg += '\n  下班：尚未打卡'

    return qr(msg, ['上班打卡', '查本月薪資'])


def handle_my_month(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return '❌ 你尚未登記。'

    ym = month_str()
    records = get_monthly_attendance(emp['id'], ym)
    if not records:
        return f'📊 {ym}\n本月尚無打卡紀錄。'

    leave_records = get_monthly_leave_records(emp['id'], ym)
    holiday_bonuses = get_monthly_holiday_bonuses(emp['id'], ym)
    s = calc_monthly_summary(emp, records, ym, leave_records=leave_records, holiday_bonuses=holiday_bonuses)
    salary_type = emp.get('salary_type') or 'hourly'

    msg = (f'📊 {ym} 出勤摘要\n'
           f'姓名：{emp["name"]}\n'
           f'出勤：{s["work_days"]} 天（{s["work_shifts"]} 班次）\n')
    if leave_records:
        msg += f'請假：{_format_leave_summary(leave_records)}\n'
    if s['total_late_minutes'] > 0:
        msg += f'遲到：{s["total_late_minutes"]} 分鐘\n'
    if s['total_overtime_minutes'] > 0:
        msg += f'加班：{s["total_overtime_minutes"]} 分鐘\n'
    msg += '\n💰 薪資估算\n'
    if salary_type == 'monthly':
        monthly_salary = emp.get('monthly_salary') or 0
        if s['pay_days'] is not None and s['total_days'] and s['pay_days'] < s['total_days']:
            msg += f'底薪：{s["base_pay"]:,} 元\n（月薪{monthly_salary:,}×{s["pay_days"]}/{s["total_days"]}天）\n'
        else:
            msg += f'底薪：{s["base_pay"]:,} 元（月薪）\n'
    else:
        msg += f'底薪：{s["base_pay"]:,} 元（時薪{emp.get("hourly_wage",200)}元×4h）\n'
    if s['overtime_pay'] > 0:
        msg += f'加班費：+{s["overtime_pay"]:,} 元\n'
    if s.get('holiday_bonus', 0) > 0:
        msg += f'假日加班：+{s["holiday_bonus"]:,} 元\n'
    if s['late_deduction'] > 0:
        msg += f'遲到扣：-{s["late_deduction"]:,} 元\n'
    if s.get('leave_deduction', 0) > 0:
        msg += f'請假扣：-{s["leave_deduction"]:,} 元\n'
    msg += f'應領：{s["net_pay"]:,} 元'
    return qr(msg, ['查打卡記錄'])


# ──────────────────────────────────────────
#  老闆功能
# ──────────────────────────────────────────

def handle_employee_list():
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。\n\n點「新增員工」建立員工資料。'
    msg = f'👥 員工列表（{len(employees)} 人）\n'
    for e in employees:
        salary_type = e.get('salary_type') or 'hourly'
        if salary_type == 'monthly':
            wage_info = f'月薪{e.get("monthly_salary") or 0:,}元'
        else:
            wage_info = f'時薪{e.get("hourly_wage") or 200}元'
        bound = '✅' if e.get('line_user_id') else '⏳未綁定'
        msg += f'\n• {e["name"]}　{wage_info}　{bound}'
    return qr(msg, ['新增員工', '補打卡', '薪資報表'])


def handle_show_salary_select(line_user_id):
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。'
    names = [e['name'] for e in employees[:10]]
    set_temp_state(line_user_id, 'boss_salary_select')
    return qr('請選擇要設定薪資的員工：', names)


def handle_show_delete_select(line_user_id):
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。'
    names = [e['name'] for e in employees[:10]]
    set_temp_state(line_user_id, 'boss_delete_select')
    return qr('請選擇要刪除的員工：', names)


def handle_set_salary_start(line_user_id, name):
    emp = get_employee_by_name(name)
    if not emp:
        return f'❌ 找不到員工「{name}」'
    set_temp_state(line_user_id, 'set_salary_type', name)
    salary_type = emp.get('salary_type') or 'hourly'
    if salary_type == 'monthly':
        current = f'目前：月薪 {emp.get("monthly_salary") or 0:,} 元'
    else:
        current = f'目前：時薪 {emp.get("hourly_wage") or 200} 元'
    return qr(f'設定 {name} 的薪資\n{current}\n\n請選擇薪資類型：', ['月薪', '時薪'])


def handle_delete_employee(name):
    emp = get_employee_by_name(name)
    if not emp:
        return f'❌ 找不到員工「{name}」'
    deactivate_employee(name)
    return f'✅ 已停用員工「{name}」'


def handle_manual_punch_start(line_user_id):
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。'
    names = [e['name'] for e in employees[:10]]
    set_temp_state(line_user_id, 'boss_manual_name')
    return qr('📝 補打卡\n請選擇員工：', names)


def handle_today_attendance():
    today = today_str()
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。'
    msg = f'📅 今日出勤 {today}\n'
    for emp in employees:
        records = get_today_all_shifts(emp['id'], today)
        if not records:
            msg += f'\n{emp["name"]}：❌ 未打卡'
        else:
            parts = []
            for r in records:
                sn = r.get('shift_number') or 1
                if r['punch_in'] and r['punch_out']:
                    parts.append(f'第{sn}班✅')
                elif r['punch_in']:
                    parts.append(f'第{sn}班🟡上班中')
            msg += f'\n{emp["name"]}：{"　".join(parts) if parts else "❌ 未打卡"}'
    return qr(msg, ['薪資報表', '員工管理'])


def handle_query_employee(name):
    emp = get_employee_by_name(name)
    if not emp:
        return f'❌ 找不到「{name}」'
    ym = month_str()
    records = get_monthly_attendance(emp['id'], ym)
    if not records:
        return f'📊 {name} {ym}\n本月尚無打卡紀錄。'
    leave_records = get_monthly_leave_records(emp['id'], ym)
    holiday_bonuses = get_monthly_holiday_bonuses(emp['id'], ym)
    s = calc_monthly_summary(emp, records, ym, leave_records=leave_records, holiday_bonuses=holiday_bonuses)
    salary_type = emp.get('salary_type') or 'hourly'

    msg = (f'📊 {name} {ym}\n'
           f'出勤：{s["work_days"]} 天（{s["work_shifts"]} 班次）\n')
    if leave_records:
        msg += f'請假：{_format_leave_summary(leave_records)}\n'
    if s['total_late_minutes'] > 0:
        msg += f'遲到：{s["total_late_minutes"]} 分鐘\n'
    if s['total_overtime_minutes'] > 0:
        msg += f'加班：{s["total_overtime_minutes"]} 分鐘\n'
    msg += '\n💰 薪資\n'
    if salary_type == 'monthly':
        monthly_salary = emp.get('monthly_salary') or 0
        if s['pay_days'] is not None and s['total_days'] and s['pay_days'] < s['total_days']:
            msg += f'底薪：{s["base_pay"]:,} 元（{monthly_salary:,}×{s["pay_days"]}/{s["total_days"]}天）\n'
        else:
            msg += f'底薪：{s["base_pay"]:,} 元（月薪{monthly_salary:,}元）\n'
    else:
        msg += f'底薪：{s["base_pay"]:,} 元\n'
    if s['overtime_pay'] > 0:
        msg += f'加班費：+{s["overtime_pay"]:,} 元\n'
    if s.get('holiday_bonus', 0) > 0:
        msg += f'假日加班：+{s["holiday_bonus"]:,} 元\n'
    if s['late_deduction'] > 0:
        msg += f'遲到扣：-{s["late_deduction"]:,} 元\n'
    if s.get('leave_deduction', 0) > 0:
        msg += f'請假扣：-{s["leave_deduction"]:,} 元\n'
    msg += f'應領：{s["net_pay"]:,} 元'
    msg += '\n\n── 每日明細 ──'
    for r in records:
        if r['punch_in']:
            day = r['date'][5:]
            sn = r.get('shift_number') or 1
            po = r['punch_out'] or '未打下班'
            late_m = f' ⚠️遲{r["late_minutes"]}分' if r.get('late_minutes', 0) and r['late_minutes'] > 0 else ''
            ot_m = f' 加{r["overtime_minutes"]}分' if r.get('overtime_minutes', 0) and r['overtime_minutes'] > 0 else ''
            manual = ' 📝' if r.get('is_manual') else ''
            msg += f'\n{day} 第{sn}班 {r["punch_in"]}-{po}{late_m}{ot_m}{manual}'
    return msg


def handle_monthly_report():
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。'
    ym = month_str()
    msg = f'💰 {ym} 薪資報表\n{"─"*18}\n'
    total = 0
    for emp in employees:
        records = get_monthly_attendance(emp['id'], ym)
        leave_recs = get_monthly_leave_records(emp['id'], ym)
        holiday_recs = get_monthly_holiday_bonuses(emp['id'], ym)
        s = calc_monthly_summary(emp, records, ym, leave_records=leave_recs, holiday_bonuses=holiday_recs)
        total += s['net_pay']
        salary_type = emp.get('salary_type') or 'hourly'
        salary_hint = '月薪' if salary_type == 'monthly' else '時薪'
        late_info = f' 遲{s["total_late_minutes"]}分' if s['total_late_minutes'] > 0 else ''
        ot_info = f' 加{s["total_overtime_minutes"]}分' if s['total_overtime_minutes'] > 0 else ''
        leave_info = f' 假{len(leave_recs)}天' if leave_recs else ''
        holiday_info = f' 假日+{s["holiday_bonus"]:,}' if s.get('holiday_bonus', 0) > 0 else ''
        shifts_info = f'{s["work_days"]}天{s["work_shifts"]}班'
        msg += f'\n{emp["name"]}（{salary_hint}）：{shifts_info}{late_info}{ot_info}{leave_info}{holiday_info}\n  應領 {s["net_pay"]:,} 元\n'
    msg += f'{"─"*18}\n全員合計：{total:,} 元'
    return qr(msg, ['今日出勤', '員工管理'])


# ──────────────────────────────────────────
#  GPS 管理
# ──────────────────────────────────────────

def _format_leave_summary(leave_records):
    counts = {}
    for r in leave_records:
        lt = r.get('leave_type', 'personal')
        counts[lt] = counts.get(lt, 0) + 1
    parts = [f'{LEAVE_TYPE_LABELS.get(k, k)}{v}天' for k, v in counts.items()]
    return '、'.join(parts)


def handle_leave_register_start(line_user_id):
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。'
    names = [e['name'] for e in employees[:10]]
    set_temp_state(line_user_id, 'boss_leave_select')
    return qr('請選擇要登記請假的員工：', names)


def handle_holiday_bonus_start(line_user_id):
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。'
    names = [e['name'] for e in employees[:10]]
    set_temp_state(line_user_id, 'boss_holiday_select')
    return qr('🎌 國定假日加班費\n請選擇員工：', names)


def handle_gps_setup_start(line_user_id):
    set_temp_state(line_user_id, 'set_store_gps')
    return qr('請分享店家位置，或直接輸入座標\n例：25.0478,121.5319\n\n📌 Google Maps 找座標：搜尋店址 → 長按地圖 → 複製上方數字', ['📍分享位置', '取消'])


def handle_gps_toggle(enable):
    store_lat = get_config('store_lat') or ''
    if enable and not store_lat:
        return '❌ 尚未設定店家位置\n請先發送「GPS設定」。'
    set_config('gps_enabled', '1' if enable else '0')
    if enable:
        radius = get_config('gps_radius_meters') or '100'
        return f'✅ GPS打卡已開啟\n範圍：{radius} 公尺'
    return '✅ GPS打卡已關閉'


def handle_gps_status():
    enabled = get_config('gps_enabled') == '1'
    lat = get_config('store_lat') or '未設定'
    lng = get_config('store_lng') or '未設定'
    radius = get_config('gps_radius_meters') or '100'
    status = '開啟 ✅' if enabled else '關閉 ❌'
    return (f'📡 GPS狀態：{status}\n'
            f'位置：{lat}, {lng}\n'
            f'範圍：{radius} 公尺')
