"""Salary estimates derived from monthly attendance totals."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SalaryEstimate:
    full_days: int
    half_days: int
    total_hours: int
    gross_salary: Decimal
    welfare_fund: Decimal
    labor_insurance: Decimal
    health_insurance: Decimal
    income_tax: Decimal
    net_salary: Decimal
    overtime_hours: int = 0
    overtime_pay: Decimal = Decimal("0")
    is_estimate: bool = True

    @property
    def total_deductions(self) -> Decimal:
        return (
            self.welfare_fund
            + self.labor_insurance
            + self.health_insurance
            + self.income_tax
        )


def calculate_salary(
    full_days: int,
    half_days: int,
    overtime_hours: int = 0,
    *,
    is_estimate: bool = True,
) -> SalaryEstimate:
    """Calculate gross pay and the specified deductions from attendance days."""

    if full_days < 0 or half_days < 0 or overtime_hours < 0:
        raise ValueError("Attendance day counts cannot be negative.")

    base_hours = full_days * 8 + half_days * 4
    total_hours = base_hours + overtime_hours
    base_gross = Decimal(base_hours * 196)
    # Standard overtime rate: 1.34x NT$196 ≈ NT$263/hr
    overtime_pay = Decimal(overtime_hours * 263)
    gross_salary = base_gross + overtime_pay

    welfare_fund = gross_salary * Decimal("0.005")
    labor_insurance = Decimal("679")
    health_insurance = Decimal("460")
    income_tax = gross_salary * Decimal("0.05")
    net_salary = (
        gross_salary
        - welfare_fund
        - labor_insurance
        - health_insurance
        - income_tax
    )

    return SalaryEstimate(
        full_days=full_days,
        half_days=half_days,
        total_hours=total_hours,
        gross_salary=gross_salary,
        welfare_fund=welfare_fund,
        labor_insurance=labor_insurance,
        health_insurance=health_insurance,
        income_tax=income_tax,
        net_salary=net_salary,
        overtime_hours=overtime_hours,
        overtime_pay=overtime_pay,
        is_estimate=is_estimate,
    )
