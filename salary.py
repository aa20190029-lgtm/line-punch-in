def calc_overtime_pay(hourly_wage, overtime_minutes):
    """
    台灣勞基法加班費：前2小時 x1.34，超過2小時 x1.67
    """
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


def calc_monthly_summary(employee, records):
    sh, sm = map(int, employee['shift_start'].split(':'))
    eh, em = map(int, employee['shift_end'].split(':'))
    normal_hours = (eh * 60 + em - sh * 60 - sm) / 60
    hourly_wage = employee['hourly_wage']

    work_days = 0
    total_late = 0
    total_ot = 0

    for r in records:
        if r['punch_in']:
            work_days += 1
            total_late += r['late_minutes'] or 0
            total_ot += r['overtime_minutes'] or 0

    base_pay = round(hourly_wage * normal_hours * work_days)
    ot_pay = calc_overtime_pay(hourly_wage, total_ot)
    late_deduct = calc_late_deduction(hourly_wage, total_late)
    net_pay = base_pay + ot_pay - late_deduct

    return {
        'work_days': work_days,
        'total_late_minutes': total_late,
        'total_overtime_minutes': total_ot,
        'normal_hours_per_day': normal_hours,
        'base_pay': base_pay,
        'overtime_pay': ot_pay,
        'late_deduction': late_deduct,
        'net_pay': net_pay,
    }
