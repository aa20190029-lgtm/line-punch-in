import pytz
from datetime import datetime

from database import (
    get_employee_by_line_id, get_employee_by_name, get_all_employees,
    add_employee, get_today_attendance, punch_in, punch_out,
    get_monthly_attendance, get_config, set_config,
    get_temp_state, set_temp_state, clear_temp_state, deactivate_employee,
)
from salary import calc_overtime_pay, calc_late_deduction, calc_monthly_summary

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
查詢 姓名 → 員工本月詳細
月報表　　→ 全員薪資報表
刪除員工 姓名 → 停用員工
班表 08:00 17:00 → 修改班表"""


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


def handle_message(line_user_id, text):
    text = text.strip()

    # 優先處理暫存狀態（等待使用者回答中）
    state, data = get_temp_state(line_user_id)
    if state:
        return handle_state(line_user_id, text, state, data)

    # 設為老闆
    if text == '設為老闆':
        boss_id = get_config('boss_line_id')
        if boss_id and boss_id != line_user_id:
            return '❌ 老闆帳號已設定。\n如需更換，請聯絡目前老闆。'
        set_config('boss_line_id', line_user_id)
        return '✅ 已將你設為老闆帳號！\n\n發送「說明」查看所有指令。'

    # 說明
    if text in ['說明', '幫助', 'help', '？', '?']:
        if is_boss(line_user_id):
            return BOSS_HELP + '\n\n' + EMPLOYEE_HELP
        emp = get_employee_by_line_id(line_user_id)
        if emp:
            return EMPLOYEE_HELP
        return '歡迎使用非晉餐廚打卡系統！\n\n請發送「加入」進行員工登記。'

    # 加入登記
    if text in ['加入', '登記', '我要登記']:
        emp = get_employee_by_line_id(line_user_id)
        if emp:
            return f'✅ 你已登記為「{emp["name"]}」\n\n發送「說明」查看打卡指令。'
        set_temp_state(line_user_id, 'register_name')
        return '📝 請輸入你的姓名（中文）：'

    # 打卡上班
    if text in ['打卡上班', '上班打卡', '上班', '上班了']:
        return handle_punch_in(line_user_id)

    # 打卡下班
    if text in ['打卡下班', '下班打卡', '下班', '下班了']:
        return handle_punch_out(line_user_id)

    # 我的今日
    if text in ['我的今日', '今日紀錄', '今天']:
        return handle_my_today(line_user_id)

    # 我的本月
    if text in ['我的本月', '本月出勤', '我的出勤']:
        return handle_my_month(line_user_id)

    # ── 老闆指令 ──────────────────────────────
    if not is_boss(line_user_id):
        emp = get_employee_by_line_id(line_user_id)
        if not emp:
            return '你尚未登記員工帳號。\n請發送「加入」登記，或聯絡老闆。'
        return None  # 員工發送不認識的指令 → 不回應

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

    return None


def handle_state(line_user_id, text, state, data):
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
        return f'✅ 登記成功！歡迎，{name}！\n班表：{s} - {e}\n\n發送「說明」查看打卡指令。'

    clear_temp_state(line_user_id)
    return None


def handle_punch_in(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return '❌ 你尚未登記。請發送「加入」登記。'

    today = today_str()
    t = time_str()
    record = get_today_attendance(emp['id'], today)

    if record and record['punch_in']:
        return f'⚠️ 今天已打過上班卡！\n打卡時間：{record["punch_in"]}'

    grace = int(get_config('late_grace_minutes') or 5)
    late = calc_late(t, emp['shift_start'], grace)
    punch_in(emp['id'], today, t, late)

    msg = f'✅ 上班打卡成功\n{emp["name"]}　{today}\n時間：{t}　（上班 {emp["shift_start"]}）'
    if late > 0:
        msg += f'\n⚠️ 遲到 {late} 分鐘'
    else:
        msg += '\n準時！'
    return msg


def handle_punch_out(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return '❌ 你尚未登記。請發送「加入」登記。'

    today = today_str()
    t = time_str()
    record = get_today_attendance(emp['id'], today)

    if not record or not record['punch_in']:
        return '❌ 今天還沒打上班卡！\n請先發送「打卡上班」。'

    if record['punch_out']:
        return f'⚠️ 今天已打過下班卡！\n下班時間：{record["punch_out"]}'

    ot = calc_overtime(t, emp['shift_end'])
    punch_out(emp['id'], today, t, ot)

    worked = worked_hours(record['punch_in'], t)
    msg = f'✅ 下班打卡成功\n{emp["name"]}　{today}\n時間：{t}\n工作 {worked:.1f} 小時'

    if ot > 0:
        ot_pay = calc_overtime_pay(emp['hourly_wage'], ot)
        msg += f'\n加班 {ot} 分鐘（+{ot_pay} 元）'
    if record['late_minutes'] and record['late_minutes'] > 0:
        deduct = calc_late_deduction(emp['hourly_wage'], record['late_minutes'])
        msg += f'\n遲到 {record["late_minutes"]} 分鐘（-{deduct} 元）'
    return msg


def handle_my_today(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return '❌ 你尚未登記。'

    today = today_str()
    r = get_today_attendance(emp['id'], today)

    if not r or not r['punch_in']:
        return f'📅 {today}\n今日尚未打上班卡。'

    msg = f'📅 {emp["name"]} 今日出勤\n上班：{r["punch_in"]}'
    if r['punch_out']:
        w = worked_hours(r['punch_in'], r['punch_out'])
        msg += f'\n下班：{r["punch_out"]}\n工作：{w:.1f} 小時'
        if r['overtime_minutes'] and r['overtime_minutes'] > 0:
            msg += f'\n加班：{r["overtime_minutes"]} 分鐘'
    else:
        msg += '\n下班：尚未打卡'
    if r['late_minutes'] and r['late_minutes'] > 0:
        msg += f'\n⚠️ 遲到：{r["late_minutes"]} 分鐘'
    return msg


def handle_my_month(line_user_id):
    emp = get_employee_by_line_id(line_user_id)
    if not emp:
        return '❌ 你尚未登記。'

    ym = month_str()
    records = get_monthly_attendance(emp['id'], ym)
    if not records:
        return f'📊 {ym} 本月尚無打卡紀錄。'

    s = calc_monthly_summary(emp, records)
    msg = (f'📊 {ym} 出勤摘要\n'
           f'姓名：{emp["name"]}\n'
           f'出勤：{s["work_days"]} 天\n')
    if s['total_late_minutes'] > 0:
        msg += f'遲到：{s["total_late_minutes"]} 分鐘\n'
    if s['total_overtime_minutes'] > 0:
        msg += f'加班：{s["total_overtime_minutes"]} 分鐘\n'
    msg += (f'\n💰 薪資估算\n'
            f'底薪：{s["base_pay"]:,} 元\n')
    if s['overtime_pay'] > 0:
        msg += f'加班費：+{s["overtime_pay"]:,} 元\n'
    if s['late_deduction'] > 0:
        msg += f'遲到扣：-{s["late_deduction"]:,} 元\n'
    msg += f'應領：{s["net_pay"]:,} 元\n（時薪 {emp["hourly_wage"]} 元）'
    return msg


def handle_employee_list():
    employees = get_all_employees()
    if not employees:
        return '目前沒有員工。\n\n請員工各自發送「加入」完成登記。'
    msg = f'👥 員工列表（{len(employees)} 人）\n'
    for e in employees:
        msg += f'\n• {e["name"]}　時薪{e["hourly_wage"]}元　{e["shift_start"]}-{e["shift_end"]}'
    return msg


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
    return msg


def handle_query_employee(name):
    emp = get_employee_by_name(name)
    if not emp:
        return f'❌ 找不到「{name}」\n發送「員工列表」查看所有員工。'
    ym = month_str()
    records = get_monthly_attendance(emp['id'], ym)
    if not records:
        return f'📊 {name} {ym}\n本月尚無打卡紀錄。'
    s = calc_monthly_summary(emp, records)
    msg = (f'📊 {name} {ym}\n'
           f'出勤：{s["work_days"]} 天\n')
    if s['total_late_minutes'] > 0:
        msg += f'遲到：{s["total_late_minutes"]} 分鐘\n'
    if s['total_overtime_minutes'] > 0:
        msg += f'加班：{s["total_overtime_minutes"]} 分鐘\n'
    msg += f'\n底薪：{s["base_pay"]:,} 元'
    if s['overtime_pay'] > 0:
        msg += f'\n加班費：+{s["overtime_pay"]:,} 元'
    if s['late_deduction'] > 0:
        msg += f'\n遲到扣：-{s["late_deduction"]:,} 元'
    msg += f'\n應領：{s["net_pay"]:,} 元'
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
        s = calc_monthly_summary(emp, records)
        total += s['net_pay']
        late_info = f' 遲{s["total_late_minutes"]}分' if s['total_late_minutes'] > 0 else ''
        ot_info = f' 加{s["total_overtime_minutes"]}分' if s['total_overtime_minutes'] > 0 else ''
        msg += f'\n{emp["name"]}：{s["work_days"]}天{late_info}{ot_info}\n  應領 {s["net_pay"]:,} 元\n'
    msg += f'{"─"*18}\n全員合計：{total:,} 元'
    return msg


def handle_shift_setting(start, end):
    try:
        datetime.strptime(start, '%H:%M')
        datetime.strptime(end, '%H:%M')
    except ValueError:
        return '❌ 時間格式錯誤，請用 HH:MM\n例如：班表 08:00 17:00'
    set_config('default_shift_start', start)
    set_config('default_shift_end', end)
    return f'✅ 班表已更新：{start} - {end}\n\n（只影響新登記的員工，既有員工班表不變）'
