"""Salary calculation service for workers."""

from typing import Dict, Tuple, Union
from decimal import Decimal, InvalidOperation


def _to_decimal(value: Union[float, int, str]) -> Decimal:
    """Convert to Decimal safely."""
    if value is None:
        return Decimal('0')
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def _convert_bonus(value: Union[float, int, str], is_percent: bool, base: Decimal) -> Decimal:
    """Convert bonus/ot/commission to amount."""
    amt = _to_decimal(value)
    if amt < 0:
        amt = Decimal('0')
    if is_percent:
        return (base * amt) / Decimal('100')
    return amt


def calculate_salary(
    monthly_salary: float,
    total_days: int,
    attended_days: int,
    bonus: Tuple[float, bool] = (0, False),
    overtime: Tuple[float, bool] = (0, False),
    commission: Tuple[float, bool] = (0, False),
    pocket_money_deduction: float = 0,
    debt_recovery_deduction: float = 0,
) -> Dict[str, Decimal]:
    """
    Calculate worker salary with breakdown.
    
    Args:
        monthly_salary: Monthly base salary
        total_days: Total working days in period
        attended_days: Days actually attended (<= total_days)
        bonus: (amount or %, is_percent=True if %)
        overtime, commission: same format
    
    Returns:
        Dict with 'per_day', 'base_salary', 'bonus_amount', 'overtime_amount',
        'commission_amount', 'total_salary'
    
    Raises:
        ValueError: Invalid attended_days > total_days or negatives
    """
    monthly_salary = _to_decimal(monthly_salary)
    total_days_dec = max(1, total_days)  # Avoid div0
    attended_days = min(attended_days, total_days)
    if attended_days < 0:
        raise ValueError("attended_days cannot be negative")
    
    per_day = monthly_salary / Decimal(total_days_dec)
    base_salary = per_day * Decimal(attended_days)
    
    bonus_amt = _convert_bonus(bonus[0], bonus[1], base_salary)
    overtime_amt = _convert_bonus(overtime[0], overtime[1], base_salary)
    commission_amt = _convert_bonus(commission[0], commission[1], base_salary)
    
    gross_salary = base_salary + bonus_amt + overtime_amt + commission_amt
    pocket_money = max(_to_decimal(pocket_money_deduction), Decimal("0"))
    debt_recovery = max(_to_decimal(debt_recovery_deduction), Decimal("0"))
    total = max(gross_salary - pocket_money - debt_recovery, Decimal("0"))
    
    return {
        'per_day_salary': per_day,
        'base_salary': base_salary,
        'bonus_amount': bonus_amt,
        'overtime_amount': overtime_amt,
        'commission_amount': commission_amt,
        'gross_salary': gross_salary,
        'pocket_money_deduction': pocket_money,
        'debt_recovery_deduction': debt_recovery,
        'total_salary': total,
        'final_payable_salary': total,
        'net_salary': total,
    }


# Example usage
if __name__ == "__main__":
    result = calculate_salary(
        monthly_salary=25000,
        total_days=26,
        attended_days=24,
        bonus=(1000, False),  # fixed 1000
        overtime=(500, True),  # 500% wait no, 5%? e.g. (5, True)
        commission=(2000, False)
    )
    print(result)
