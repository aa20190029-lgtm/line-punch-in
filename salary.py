import calendar
from datetime import date

HOURS_PER_SHIFT = 4  # 每班固定 4 小時（10:30-14:30 或 16:30-20:30）


def roc_to_iso(roc_str):
    """民國年字串 YYYMMDD → 西元 YYYY-MM-DD，失敗回 None"""
    roc_str = ''.join(c for c in roc_str if c.isdigit())
    if len(roc_str) != 7:
        return None
    try:
        roc_year = int(roc_str[:3])
        month = int(roc_str[3:5])
        day = int(roc_str[5:7])
        d = date(roc_year + 1911, month, day)
        return d.isoformat()
    except ValueError:
        return None


def calc_overtime_pay(hourly_wage, overtime_minutes):
    """勞基法加班費：前2小時1.34倍，之後1.67倍，按分鐘精算"""
    if overtime_minutes <= 0:
        return 0
    hours = overtime_minutes / 60
    if hours <= 2:
        pay = hourly_wage * hours * (4 / 3)
    else:
        pay = hourly_wage * 2 * (4 / 3) + hourly_wage * (hours - 2) * (5 / 3)
    return round(pay)


def calc_late_deduction(hourly_wage, late_minutes):
    if late_minutes <= 0:
        return 0
    return round(hourly_wage * (late_minutes / 60))


def calc_leave_deduction(monthly_salary, leave_days):
    """請假扣款：月薪 ÷ 30 × 請假天數（勞基法100%扣）"""
    if leave_days <= 0:
        return 0
    return round(monthly_salary / 30 * leave_days)


def calc_monthly_summary(employee, records, year_month=None, leave_days=0):
    salary_type = employee.get('salary_type') or 'hourly'
    if salary_type == 'monthly':
        return _calc_monthly_salary(employee, records, year_month, leave_days)
    return _calc_hourly_salary(employee, records)


def _calc_hourly_salary(employee, records):
    hourly_wage = employee.get('hourly_wage') or 200

    work_shifts = total_late = total_ot = 0
    unique_dates = set()
    for r in records:
        if r['punch_in']:
            work_shifts += 1
            total_late += r.get('late_minutes') or 0
            total_ot += r.get('overtime_minutes') or 0
            unique_dates.add(r['date'])

    work_days = len(unique_dates)
    base_pay = round(hourly_wage * HOURS_PER_SHIFT * work_shifts)
    ot_pay = calc_overtime_pay(hourly_wage, total_ot)
    late_deduct = calc_late_deduction(hourly_wage, total_late)

    return {
        'salary_type': 'hourly',
        'work_days': work_days,
        'work_shifts': work_shifts,
        'total_late_minutes': total_late,
        'total_overtime_minutes': total_ot,
        'base_pay': base_pay,
        'overtime_pay': ot_pay,
        'late_deduction': late_deduct,
        'net_pay': base_pay + ot_pay - late_deduct,
        'hourly_rate': hourly_wage,
        'pay_days': None,
        'total_days': None,
    }


def _calc_monthly_salary(employee, records, year_month, leave_days=0):
    monthly_salary = employee.get('monthly_salary') or 0
    hourly_rate = monthly_salary / 240  # 30天 × 8小時

    work_shifts = total_late = total_ot = 0
    unique_dates = set()
    for r in records:
        if r['punch_in']:
            work_shifts += 1
            total_late += r.get('late_minutes') or 0
            total_ot += r.get('overtime_minutes') or 0
            unique_dates.add(r['date'])

    work_days = len(unique_dates)
    pay_days = total_days = None
    if year_month:
        year, month = map(int, year_month.split('-'))
        total_days = calendar.monthrange(year, month)[1]
        pay_days = total_days

        hire_date_str = (employee.get('hire_date') or '').strip()
        if hire_date_str:
            try:
                hd = date.fromisoformat(hire_date_str)
                hd_ym = f'{hd.year}-{hd.month:02d}'
                if hd_ym == year_month:
                    pay_days = total_days - hd.day + 1
                elif hd_ym > year_month:
                    pay_days = 0
            except ValueError:
                pass

    if total_days:
        base_pay = round(monthly_salary * pay_days / total_days)
    else:
        base_pay = monthly_salary

    ot_pay = calc_overtime_pay(hourly_rate, total_ot)
    late_deduct = round(hourly_rate * total_late / 60)
    leave_deduct = calc_leave_deduction(monthly_salary, leave_days)

    return {
        'salary_type': 'monthly',
        'work_days': work_days,
        'work_shifts': work_shifts,
        'total_late_minutes': total_late,
        'total_overtime_minutes': total_ot,
        'leave_days': leave_days,
        'base_pay': base_pay,
        'overtime_pay': ot_pay,
        'late_deduction': late_deduct,
        'leave_deduction': leave_deduct,
        'net_pay': base_pay + ot_pay - late_deduct - leave_deduct,
        'hourly_rate': round(hourly_rate),
        'pay_days': pay_days,
        'total_days': total_days,
    }
