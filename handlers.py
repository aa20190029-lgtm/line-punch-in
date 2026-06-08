import math
import pytz
from datetime import datetime

from database import (
    get_employee_by_line_id, get_employee_by_name, get_all_employees,
    add_employee, get_today_attendance, punch_in, punch_out,
    get_monthly_attendance, get_config, set_config,
    get_temp_state, set_temp_state, clear_temp_state, deactivate_employee,
    update_employee_salary, update_employee_hire_date,
)
from salary import calc_overtime_pay, calc_late_deduction, calc_monthly_summary, roc_to_iso

TZ = pytz.timezone('Asia/Taipei')

EMPLOYEE_HELP = """📋 打卡指令：
打卡上班 → 上班打卡
打卡下班 → 下班打卡
我的今日 → 今日紀錄
我的本月 → 本月出勤摘要

首次使用請發送：加入"""

BOSS_HELP = """👔 老闆指令：
員工列表　→ 查看所有員工
今日出勤　→ 今天打卡狀況
查詢 姓名　→ 員工本月詳細
月報表　　→ 全員薪資報表
刪除員工 姓名 → 停用員工
班表 08:00 17:00 → 修改預設班表
設定薪資 姓名 → 設定薪資類型
GPS設定　→ 設定店家位置
GPS開啟/關閉 → 切換GPS打卡"""


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


def handle_message(line_user_id, text):
    text = text.strip()

    state, data = get_temp_state(line_user_id)
    if state:
        return handle_state(line_user_id, text, state, data)

    if text == '設為老闆':
        boss_id = get_config('boss_line_id')
        if boss_id and boss_id != line_user_id:
            return '❌ 老闆帳號已設定。\n如需更換，請聯絡目前老闆。'
        set_config('boss_line_id', line_user_id)
        return qr('✅ 已將你設為老闆帳號！\n\n發送「說明」查看所有指令。', ['說明'])

    if text in ['說明', '幫助', 'help', '？', '?']:
        if is_boss(line_user_id):
            return qr(BOSS_HELP + '\n\n' + EMPLOYEE_HELP, ['今日出勤', '月報表', '員工列表'])
        emp = get_employee_by_line_id(line_user_id)
        if emp:
            return qr(EMPLOYEE_HELP, ['打卡上班', '打卡下班', '我的今日', '我的本月'])
        return qr('歡迎使用非晉餐廚打卡系統！\n\n請發送「加入」進行員工登記。', ['加入'])

    if text in ['加入', '登記', '我要登記']:
        emp = get_employee_by_line_id(line_user_id)
        if emp:
            return qr(f'✅ 你已登記為「{emp["name"]}」\n\n發送「說明」查看打卡指令。', ['打卡上班', '我的今日'])
        set_temp_state(line_user_id, 'register_name')
        return '📝 請輸入你的姓名（中文）：'

    if text in ['打卡上班', '上班打卡', '上班', '上班了']:
        return handle_punch_in(line_user_id)

    if text in ['打卡下班', '下班打卡', '下班', '下班了']:
        return handle_punch_out(line_user_id)

    if text in ['我的今日', '今日紀錄', '今天']:
        return handle_my_today(line_user_id)

    if text in ['我的本月', '本月出勤', '我的出勤']:
        return handle_my_month(line_user_id)

    if not is_boss(line_user_id):
        emp = get_employee_by_line_id(line_user_id)
        if not emp:
            return qr('你尚未登記員工帳號。\n請發送「加入」登記，或聯絡老闆。', ['加入'])
        return None

    if text in ['員工列表', '人員列表']:
        return handle_employee_list()

    if text in ['今日出勤', '今天出勤']:
        return handle_today_attendance()

    if text in ['月報表', '薪資報表']:
        return handle_monthly_report()

    if text.startswith('查詢 ') or text.startswith('查詢　'):
        name = text.replace('查詢', '').strip()
        return handle_query_employee(name)

    if text.startswith('刪除員工 ') or text.startswith('刪除員工　'):
        name = text.replace('刪除員工', '').strip()
        return handle_delete_employee(name)

    if text.startswith('班表 '):
        parts = text.split()
        if len(parts) == 3:
            return handle_shift_setting(parts[1], parts[2])
        return '格式：班表 08:00 17:00'

    if text == '班表設定':
        s = get_config('default_shift_start')
        e = get_config('default_shift_end')
        return f'目前班表：{s} - {e}\n\n修改格式：班表 08:00 17:00'

    if text.startswith('設定薪資 ') or text.startswith('設定薪資　'):
        name = text.replace('設定薪資', '').strip()
        return handle_set_salary_start(line_user_id, name)

    if text == 'GPS設定':
        return handle_gps_setup_start(line_user_id)

    if text == 'GPS開啟':
        return handle_gps_toggle(True)

    if text == 'GPS關閉':
        return handle_gps_toggle(False)

    if text == 'GPS狀態':
        return handle_gps_status()

    return None


def handle_state(line_user_id, text, state, data):
    # 等待分享位置（員工打卡或老闆設GPS）→ 只處理取消，其餘提醒
    if state == 'pending_punch_in':
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消打卡。'
        return qr('請先分享你的位置以完成打卡\n或輸入「取消」放棄', ['📍分享位置', '取消'])

    if state == 'pending_punch_out':
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消打卡。'
        return qr('請先分享你的位置以完成打卡\n或輸入「取消」放棄', ['📍分享位置', '取消'])

    if state == 'set_store_gps':
        if text in ['取消', '算了']:
            clear_temp_state(line_user_id)
            return '已取消GPS設定。'
        return qr('請分享店家位置（點選「📍分享位置」按鈕）', ['📍分享位置', '取消'])

    # 員工登記姓名
    if state == 'register_name':
        name = text.strip()
        if not name or len(name) > 10 or not any('一' <= c <= '鿿' for c in name):
            clear_temp_state(line_user_id)
            return '❌ 請輸入中文姓名（10字以內）。\n發送「加入」重試。'
        existing = get_employee_by_name(name)
        if existing:
            clear_temp_state(line_user_id)
            return f'❌ 「{name}」已被登記，請換一個名字。\n發送「加入」重試。'
        add_employee(line_user_id, name)
        clear_temp_state(line_user_id)
        s = get_config('default_shift_start')
        e = get_config('default_shift_end')
        return qr(f'✅ 登記成功！歡迎，{name}！\n班表：{s} - {e}\n\n發送「說明」查看打卡指令。', ['打卡上班', '說明'])

    # 設定薪資 step1：選月薪/時薪
    if state == 'set_salary_type':
        name = data
        if text == '月薪':
            set_temp_state(line_user_id, 'set_salary_amount', f'{name},monthly')
            return f'請輸入 {name} 的月薪金額（如：38000）：'
        elif text == '時薪':
            set_temp_state(line_user_id, 'set_salary_amount', f'{name},hourly')
            return f'請輸入 {name} 的時薪金額（如：200）：'
        else:
            clear_temp_state(line_user_id)
            return '❌ 請輸入「月薪」或「時薪」。\n發送「設定薪資 姓名」重試。'

    # 設定薪資 step2：輸入金額
    if state == 'set_salary_amount':
        parts = data.split(',', 1)
        name, salary_type = parts[0], parts[1]
        try:
            amount = int(text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            clear_temp_state(line_user_id)
            return '❌ 請輸入有效金額（如：38000）。\n發送「設定薪資 姓名」重試。'
        set_temp_state(line_user_id, 'set_salary_hire_date', f'{name},{salary_type},{amount}')
        hint = '月薪' if salary_type == 'monthly' else '時薪'
        return (f'已記錄 {name} {hint} {amount:,} 元\n\n'
                f'請輸入入職日（民國年月日，如：1130601）\n不需要請輸入「略過」：')

    # 設定薪資 step3：入職日
    if state == 'set_salary_hire_date':
        parts = data.split(',', 2)
        name, salary_type, amount = parts[0], parts[1], int(parts[2])

        if salary_type == 'monthly':
            update_employee_salary(name, 'monthly', monthly_salary=amount)
        else:
            update_employee_salary(name, 'hourly', hourly_wage=amount)

        hire_date_iso = None
        if text.strip() not in ['略過', '跳過', '不用', '無', '沒有']:
            hire_date_iso = roc_to_iso(text.strip())

        if hire_date_iso:
            update_employee_hire_date(name, hire_date_iso)

        clear_temp_state(line_user_id)
        hint = '月薪' if salary_type == 'monthly' else '時薪'
        hire_msg = f'\n入職日：{hire_date_iso}' if hire_date_iso else ''
        warn = ''
        if text.strip() not in ['略過', '跳過', '不用', '無', '沒有'] and not hire_date_iso:
            warn = '\n⚠️ 入職日格式有誤，已略過（格式：民國年月日，如 1130601）'
        return f'✅ {name} 薪資已設定\n類型：{hint}\n金額：{amount:,} 元{hire_msg}{warn}'

    # GPS 設定半徑（老闆分享位置後再輸入公尺數）
    if state == 'set_store_gps_radius':
        try:
            radius = int(text.strip())
            if radius <= 0:
                raise ValueError
        except ValueError:
            clear_temp_state(line_user_id)
            return '❌ 請輸入有效公尺數（如：100）。\n發送「GPS設定」重試。'
        lat_lng = data.split(',', 1)
        lat, lng = float(lat_lng[0]), float(lat_lng[1])
        set_config('store_lat', str(lat))
        set_config('store_lng', str(lng))
        set_config('gps_radius_meters', str(radius))
        clear_temp_state(line_user_id)
        return (f'✅ GPS設定完成\n'
                f'位置：{lat:.6f}, {lng:.6f}\n'
                f'範圍：{radius} 公尺\n\n'
                f'發送「GPS開啟」啟用GPS打卡。')

    clear_temp_state(line_user_id)
    return None


def handle_location(line_user_id, lat, lng):
    state, data = get_temp_state(line_user_id)

    # 老闆設定店家位置
    if is_boss(line_user_id) and state == 'set_store_gps':
        set_temp_state(line_user_id, 'set_store_gps_radius', f'{lat},{lng}')
        return (f'✅ 已收到店家位置\n'
                f'緯度：{lat:.6f}\n'
                f'經度：{lng:.6f}\n\n'
                f'請輸入打卡範圍（公尺，建議100）：')

    # 員工 GPS 打卡
    if state in ('pending_punch_in', 'pending_punch_out'):
        store_lat_str = get_config('store_lat') or ''
        store_lng_str = get_config('store_lng') or ''
        if not store_lat_str or not store_lng_str:
            clear_temp_state(line_user_id)
            return '❌ 店家位置尚未設定，請聯絡老闆。'

        store_lat = float(store_lat_str)
        store_lng = float(store_lng_str)
        radius = float(get_config('gps_radius_meters') or 100)
        dist = haversine_distance(lat, lng, store_lat, store_lng)

        if dist > radius:
            clear_temp_state(line_user_id)
            return (f'❌ 位置不在打卡範圍內\n'
                    f'你距店家 {dist:.0f} 公尺\n'
                    f'需在 {radius:.0f} 公尺以內\n\n'
                    f'請到店內重新打卡。')

        clear_temp_state(line_user_id)
        if state == 'pending_punch_in':
            return _do_punch_in(line_user_id)
        else:
            return _do_punch_out(line_user_id)

    return None


def handle_punch_in(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return qr('❌ 你尚未登記。請發送「加入」登記。', ['加入'])

    today = today_str()
    record = get_today_attendance(emp['id'], today)
    if record and record['punch_in']:
        return f'⚠️ 今天已打過上班卡！\n打卡時間：{record["punch_in"]}'

    gps_enabled = get_config('gps_enabled') == '1'
    if gps_enabled:
        set_temp_state(line_user_id, 'pending_punch_in')
        return qr('📍 GPS打卡已啟用\n請分享你的位置以完成上班打卡：', ['📍分享位置'])

    return _do_punch_in(line_user_id)


def handle_punch_out(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return qr('❌ 你尚未登記。請發送「加入」登記。', ['加入'])

    today = today_str()
    record = get_today_attendance(emp['id'], today)
    if not record or not record['punch_in']:
        return '❌ 今天還沒打上班卡！\n請先發送「打卡上班」。'
    if record['punch_out']:
        return f'⚠️ 今天已打過下班卡！\n下班時間：{record["punch_out"]}'

    gps_enabled = get_config('gps_enabled') == '1'
    if gps_enabled:
        set_temp_state(line_user_id, 'pending_punch_out')
        return qr('📍 GPS打卡已啟用\n請分享你的位置以完成下班打卡：', ['📍分享位置'])

    return _do_punch_out(line_user_id)


def _do_punch_in(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    today = today_str()
    t = time_str()
    grace = int(get_config('late_grace_minutes') or 5)
    late = calc_late(t, emp['shift_start'], grace)
    punch_in(emp['id'], today, t, late)

    msg = f'✅ 上班打卡成功\n{emp["name"]}　{today}\n時間：{t}　（班表 {emp["shift_start"]}）'
    if late > 0:
        msg += f'\n⚠️ 遲到 {late} 分鐘'
    else:
        msg += '\n準時！'
    return qr(msg, ['打卡下班', '我的今日'])


def _do_punch_out(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    today = today_str()
    t = time_str()
    record = get_today_attendance(emp['id'], today)

    ot = calc_overtime(t, emp['shift_end'])
    punch_out(emp['id'], today, t, ot)
    worked = worked_hours(record['punch_in'], t)

    salary_type = emp.get('salary_type') or 'hourly'
    if salary_type == 'monthly':
        monthly_salary = emp.get('monthly_salary') or 0
        hourly_rate = monthly_salary / 240
    else:
        hourly_rate = emp['hourly_wage'] or 200

    msg = f'✅ 下班打卡成功\n{emp["name"]}　{today}\n時間：{t}\n工作 {worked:.1f} 小時'
    if ot > 0:
        ot_pay = calc_overtime_pay(hourly_rate, ot)
        msg += f'\n加班 {ot} 分鐘（+{ot_pay} 元）'
    if record and record['late_minutes'] and record['late_minutes'] > 0:
        late_deduct = calc_late_deduction(hourly_rate, record['late_minutes'])
        msg += f'\n遲到 {record["late_minutes"]} 分鐘（-{late_deduct} 元）'
    return qr(msg, ['我的今日', '我的本月'])


def handle_my_today(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return '❌ 你尚未登記。'

    today = today_str()
    r = get_today_attendance(emp['id'], today)

    if not r or not r['punch_in']:
        return qr(f'📅 {today}\n今日尚未打上班卡。', ['打卡上班'])

    msg = f'📅 {emp["name"]} 今日出勤\n上班：{r["punch_in"]}'
    if r['punch_out']:
        w = worked_hours(r['punch_in'], r['punch_out'])
        msg += f'\n下班：{r["punch_out"]}\n工作：{w:.1f} 小時'
        if r['overtime_minutes'] and r['overtime_minutes'] > 0:
            msg += f'\n加班：{r["overtime_minutes"]} 分鐘'
        buttons = ['我的本月']
    else:
        msg += '\n下班：尚未打卡'
        buttons = ['打卡下班', '我的本月']
    if r['late_minutes'] and r['late_minutes'] > 0:
        msg += f'\n⚠️ 遲到：{r["late_minutes"]} 分鐘'
    return qr(msg, buttons)


def handle_my_month(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return '❌ 你尚未登記。'

    ym = month_str()
    records = get_monthly_attendance(emp['id'], ym)
    if not records:
        return f'📊 {ym} 本月尚無打卡紀錄。'

    s = calc_monthly_summary(emp, records, ym)
    salary_type = emp.get('salary_type') or 'hourly'

    msg = (f'📊 {ym} 出勤摘要\n'
           f'姓名：{emp["name"]}\n'
           f'出勤：{s["work_days"]} 天\n')
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
        msg += f'底薪：{s["base_pay"]:,} 元（時薪{emp["hourly_wage"]}元）\n'
    if s['overtime_pay'] > 0:
        msg += f'加班費：+{s["overtime_pay"]:,} 元\n'
    if s['late_deduction'] > 0:
        msg += f'遲到扣：-{s["late_deduction"]:,} 元\n'
    msg += f'應領：{s["net_pay"]:,} 元'
    return qr(msg, ['我的今日'])


def handle_employee_list():
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。\n\n請員工各自發送「加入」完成登記。'
    msg = f'👥 員工列表（{len(employees)} 人）\n'
    for e in employees:
        salary_type = e.get('salary_type') or 'hourly'
        if salary_type == 'monthly':
            monthly = e.get('monthly_salary') or 0
            wage_info = f'月薪{monthly:,}元'
        else:
            wage_info = f'時薪{e["hourly_wage"]}元'
        msg += f'\n• {e["name"]}　{wage_info}　{e["shift_start"]}-{e["shift_end"]}'
    return qr(msg, ['今日出勤', '月報表'])


def handle_delete_employee(name):
    emp = get_employee_by_name(name)
    if not emp:
        return f'❌ 找不到員工「{name}」'
    deactivate_employee(name)
    return f'✅ 已停用員工「{name}」'


def handle_today_attendance():
    today = today_str()
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。'
    msg = f'📅 今日出勤 {today}\n'
    for emp in employees:
        r = get_today_attendance(emp['id'], today)
        if not r or not r['punch_in']:
            status = '❌ 未打卡'
        elif not r['punch_out']:
            status = f'🟡 上班 {r["punch_in"]}'
        else:
            status = f'✅ {r["punch_in"]}-{r["punch_out"]}'
        late = f' ⚠️遲{r["late_minutes"]}分' if r and r.get('late_minutes', 0) and r['late_minutes'] > 0 else ''
        msg += f'\n{emp["name"]}：{status}{late}'
    return qr(msg, ['月報表', '員工列表'])


def handle_query_employee(name):
    emp = get_employee_by_name(name)
    if not emp:
        return f'❌ 找不到「{name}」\n發送「員工列表」查看所有員工。'
    ym = month_str()
    records = get_monthly_attendance(emp['id'], ym)
    if not records:
        return f'📊 {name} {ym}\n本月尚無打卡紀錄。'
    s = calc_monthly_summary(emp, records, ym)
    salary_type = emp.get('salary_type') or 'hourly'

    msg = (f'📊 {name} {ym}\n'
           f'出勤：{s["work_days"]} 天\n')
    if s['total_late_minutes'] > 0:
        msg += f'遲到：{s["total_late_minutes"]} 分鐘\n'
    if s['total_overtime_minutes'] > 0:
        msg += f'加班：{s["total_overtime_minutes"]} 分鐘\n'
    msg += '\n💰 薪資\n'
    if salary_type == 'monthly':
        monthly_salary = emp.get('monthly_salary') or 0
        if s['pay_days'] is not None and s['total_days'] and s['pay_days'] < s['total_days']:
            msg += f'底薪：{s["base_pay"]:,} 元（月薪{monthly_salary:,}×{s["pay_days"]}/{s["total_days"]}天）\n'
        else:
            msg += f'底薪：{s["base_pay"]:,} 元（月薪{monthly_salary:,}元）\n'
    else:
        msg += f'底薪：{s["base_pay"]:,} 元\n'
    if s['overtime_pay'] > 0:
        msg += f'加班費：+{s["overtime_pay"]:,} 元\n'
    if s['late_deduction'] > 0:
        msg += f'遲到扣：-{s["late_deduction"]:,} 元\n'
    msg += f'應領：{s["net_pay"]:,} 元'
    msg += '\n\n── 每日明細 ──'
    for r in records:
        if r['punch_in']:
            day = r['date'][5:]
            po = r['punch_out'] or '未打下班'
            late_m = f' ⚠️遲{r["late_minutes"]}分' if r.get('late_minutes', 0) and r['late_minutes'] > 0 else ''
            ot_m = f' 加{r["overtime_minutes"]}分' if r.get('overtime_minutes', 0) and r['overtime_minutes'] > 0 else ''
            msg += f'\n{day} {r["punch_in"]}-{po}{late_m}{ot_m}'
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
        s = calc_monthly_summary(emp, records, ym)
        total += s['net_pay']
        salary_type = emp.get('salary_type') or 'hourly'
        salary_hint = '月薪' if salary_type == 'monthly' else '時薪'
        late_info = f' 遲{s["total_late_minutes"]}分' if s['total_late_minutes'] > 0 else ''
        ot_info = f' 加{s["total_overtime_minutes"]}分' if s['total_overtime_minutes'] > 0 else ''
        msg += f'\n{emp["name"]}（{salary_hint}）：{s["work_days"]}天{late_info}{ot_info}\n  應領 {s["net_pay"]:,} 元\n'
    msg += f'{"─"*18}\n全員合計：{total:,} 元'
    return qr(msg, ['今日出勤', '員工列表'])


def handle_shift_setting(start, end):
    try:
        datetime.strptime(start, '%H:%M')
        datetime.strptime(end, '%H:%M')
    except ValueError:
        return '❌ 時間格式錯誤，請用 HH:MM\n例如：班表 08:00 17:00'
    set_config('default_shift_start', start)
    set_config('default_shift_end', end)
    return f'✅ 班表已更新：{start} - {end}\n\n（只影響新登記的員工，既有員工班表不變）'


def handle_set_salary_start(line_user_id, name):
    emp = get_employee_by_name(name)
    if not emp:
        return f'❌ 找不到員工「{name}」\n發送「員工列表」查看所有員工。'
    set_temp_state(line_user_id, 'set_salary_type', name)
    salary_type = emp.get('salary_type') or 'hourly'
    if salary_type == 'monthly':
        current = f'目前：月薪 {emp.get("monthly_salary") or 0:,} 元'
    else:
        current = f'目前：時薪 {emp["hourly_wage"]} 元'
    return qr(f'設定 {name} 的薪資\n{current}\n\n請選擇薪資類型：', ['月薪', '時薪'])


def handle_gps_setup_start(line_user_id):
    set_temp_state(line_user_id, 'set_store_gps')
    return qr('請分享店家的位置\n（在店內點選「📍分享位置」按鈕）', ['📍分享位置'])


def handle_gps_toggle(enable):
    store_lat = get_config('store_lat') or ''
    store_lng = get_config('store_lng') or ''
    if enable and (not store_lat or not store_lng):
        return '❌ 尚未設定店家位置\n請先發送「GPS設定」並分享位置。'
    set_config('gps_enabled', '1' if enable else '0')
    if enable:
        radius = get_config('gps_radius_meters') or '100'
        return f'✅ GPS打卡已開啟\n範圍：{radius} 公尺\n\n員工打卡時需分享位置。'
    return '✅ GPS打卡已關閉\n員工可直接文字打卡。'


def handle_gps_status():
    enabled = get_config('gps_enabled') == '1'
    lat = get_config('store_lat') or '未設定'
    lng = get_config('store_lng') or '未設定'
    radius = get_config('gps_radius_meters') or '100'
    status = '開啟 ✅' if enabled else '關閉 ❌'
    return (f'📡 GPS打卡狀態：{status}\n'
            f'店家位置：{lat}, {lng}\n'
            f'範圍：{radius} 公尺')
