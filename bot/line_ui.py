"""LINE Flex message templates for the CSIE Student Portal."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from linebot.v3.messaging import (
    FlexContainer,
    FlexMessage,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
)

from attendance.salary import SalaryEstimate

CARD_BG = "#F1F5E9"
DARK_GREEN = "#1E421E"
BUTTON_GREEN = "#264E22"
MUTED_TEXT = "#6E7D6E"
LABEL_TEXT = "#556555"
DEDUCTION_RED = "#8E3535"
DIVIDER_COLOR = "#D6DDD2"
BADGE_BG = "#E2E8DC"
BADGE_TEXT = "#304030"


def _pill(text: str, *, bg: str = BADGE_BG, color: str = BADGE_TEXT) -> dict[str, object]:
    """Build a rounded pill badge with auto-shrink sizing to prevent text cropping."""
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": bg,
        "cornerRadius": "xxl",
        "paddingStart": "8px",
        "paddingEnd": "8px",
        "paddingTop": "2px",
        "paddingBottom": "2px",
        "flex": 0,
        "contents": [
            {
                "type": "text",
                "text": text,
                "size": "xxs",
                "color": color,
                "weight": "bold",
                "align": "center",
                "wrap": False,
            }
        ],
    }


def _stat_row(
    label: str,
    value: str,
    *,
    value_color: str = DARK_GREEN,
    bold: bool = True,
    margin: str = "sm",
    label_flex: int = 4,
    value_flex: int = 3,
) -> dict[str, object]:
    """Build a two-column key-value row."""
    return {
        "type": "box",
        "layout": "horizontal",
        "margin": margin,
        "contents": [
            {
                "type": "text",
                "text": label,
                "size": "sm",
                "color": LABEL_TEXT,
                "flex": label_flex,
                "wrap": True,
            },
            {
                "type": "text",
                "text": value,
                "size": "sm",
                "color": value_color,
                "weight": "bold" if bold else "regular",
                "align": "end",
                "flex": value_flex,
                "wrap": True,
            },
        ],
    }


def _button(
    label: str,
    data: str,
    *,
    display_text: str | None = None,
    color: str = BUTTON_GREEN,
    margin: str = "md",
) -> dict[str, object]:
    action = PostbackAction(label=label, data=data, display_text=display_text or label)
    return {
        "type": "button",
        "style": "primary",
        "color": color,
        "height": "sm",
        "margin": margin,
        "action": action.to_dict(),
    }


# ======================================================================
# 1. Salary Overview (Exact Match for Image 2)
# ======================================================================

def salary_overview_message(
    estimate: SalaryEstimate,
    *,
    month_label: str,
    target_month_key: str | None = None,
) -> FlexMessage:
    """Build the Salary Overview card matching the leave recorded design."""
    badge_label = "Est." if estimate.is_estimate else "Verified"
    month_key = target_month_key or month_label

    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                # Header row: Title + Badge
                {
                    "type": "box",
                    "layout": "horizontal",
                    "alignItems": "center",
                    "contents": [
                        {
                            "type": "text",
                            "text": "Salary Overview",
                            "weight": "bold",
                            "size": "xl",
                            "color": DARK_GREEN,
                            "flex": 1,
                        },
                        _pill(badge_label),
                    ],
                },
                # Subtitle
                {
                    "type": "text",
                    "text": f"{month_label} · Sample figures",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                # Take-Home Label & Big Amount
                {
                    "type": "text",
                    "text": "Estimated Take-Home Pay",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "lg",
                },
                {
                    "type": "text",
                    "text": f"NT${int(estimate.net_salary):,}",
                    "size": "3xl",
                    "weight": "bold",
                    "color": DARK_GREEN,
                    "margin": "xs",
                },
                # Divider
                {
                    "type": "separator",
                    "color": DIVIDER_COLOR,
                    "margin": "lg",
                },
                # Metrics
                _stat_row("Gross earnings", f"${int(estimate.gross_salary):,}", margin="md"),
                _stat_row(
                    "Estimated deductions",
                    f"-${int(estimate.total_deductions):,}",
                    value_color=DEDUCTION_RED,
                    margin="sm",
                ),
                _stat_row("Worked hours", f"{estimate.total_hours} hrs", margin="sm"),
                # Action button
                _button(
                    "View Salary Breakdown",
                    f"action=salary_breakdown&month={month_key}",
                    margin="xl",
                ),
            ],
        },
    }
    return FlexMessage(
        alt_text=f"Salary Overview: NT${int(estimate.net_salary):,} ({month_label})",
        contents=FlexContainer.from_dict(bubble),
    )


# Backward-compatible alias
salary_inquiry_message = salary_overview_message


def salary_breakdown_message(
    estimate: SalaryEstimate,
    *,
    month_label: str,
) -> FlexMessage:
    """Build the detailed deduction breakdown and overtime calculator card."""
    def fmt(val: Decimal) -> str:
        return f"NT${val:,.2f}"

    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "alignItems": "center",
                    "contents": [
                        {
                            "type": "text",
                            "text": "Salary Breakdown",
                            "weight": "bold",
                            "size": "xl",
                            "color": DARK_GREEN,
                            "flex": 1,
                        },
                        _pill("Est." if estimate.is_estimate else "Verified"),
                    ],
                },
                {
                    "type": "text",
                    "text": f"{month_label} · Itemized Statement",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                # Inner white card with itemized breakdown
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "md",
                    "paddingAll": "14px",
                    "margin": "md",
                    "contents": [
                        _stat_row(
                            "Attendance logged",
                            f"{estimate.full_days} full, {estimate.half_days} half ({estimate.total_hours}h)",
                            margin="none",
                        ),
                        _stat_row("Gross earnings (NT$196/h)", fmt(estimate.gross_salary), margin="xs"),
                        {"type": "separator", "color": DIVIDER_COLOR, "margin": "sm"},
                        _stat_row("Labor Insurance", f"-{fmt(estimate.labor_insurance)}", value_color=DEDUCTION_RED, bold=False, margin="sm"),
                        _stat_row("Health Insurance", f"-{fmt(estimate.health_insurance)}", value_color=DEDUCTION_RED, bold=False, margin="xs"),
                        _stat_row("Income Tax (5%)", f"-{fmt(estimate.income_tax)}", value_color=DEDUCTION_RED, bold=False, margin="xs"),
                        _stat_row("Welfare Fund (0.5%)", f"-{fmt(estimate.welfare_fund)}", value_color=DEDUCTION_RED, bold=False, margin="xs"),
                        {"type": "separator", "color": DIVIDER_COLOR, "margin": "sm"},
                        _stat_row("Total Deductions", f"-{fmt(estimate.total_deductions)}", value_color=DEDUCTION_RED, margin="sm"),
                        _stat_row("Net Take-Home Pay", fmt(estimate.net_salary), value_color=DARK_GREEN, margin="sm"),
                    ],
                },
                {
                    "type": "text",
                    "text": (
                        "*Calculated figures are estimates based on logged hours. "
                        "Overtime rate is 1.34x (NT$263/hr) and can be requested in Help Center."
                    ),
                    "size": "xxs",
                    "color": MUTED_TEXT,
                    "wrap": True,
                    "margin": "sm",
                },
                _button("Back to Overview", f"action=salary&month={month_label}", margin="md"),
            ],
        },
    }
    return FlexMessage(
        alt_text=f"Salary Breakdown: {month_label}",
        contents=FlexContainer.from_dict(bubble),
    )


# ======================================================================
# 2. My Attendance (Exact Match for Image 3)
# ======================================================================

def my_attendance_message(
    summary: dict[str, object],
    *,
    month_label: str,
) -> FlexMessage:
    """Build the My Attendance card matching Image 3 with Month-to-Date calculation."""
    pct = summary.get("attendance_pct")
    if pct is None:
        pct_str = "N/A"
        bar_contents: list[dict[str, object]] = []
    else:
        pct_val = int(pct)
        pct_str = f"{pct_val}%"
        bar_width = max(5, min(100, pct_val))
        bar_contents = [
            {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": BUTTON_GREEN,
                "width": f"{bar_width}%",
                "height": "8px",
                "cornerRadius": "30px",
                "contents": [],
            }
        ]

    absent_count = int(summary.get("absent_days", 0) or 0)
    absent_color = DEDUCTION_RED if absent_count > 0 else DARK_GREEN

    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "My Attendance",
                    "weight": "bold",
                    "size": "xl",
                    "color": DARK_GREEN,
                },
                {
                    "type": "text",
                    "text": month_label,
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                # Attendance Rate Label & Percentage
                {
                    "type": "text",
                    "text": "Attendance Rate (Month-to-Date)",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "weight": "bold",
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": pct_str,
                    "size": "3xl",
                    "weight": "bold",
                    "color": DARK_GREEN,
                    "margin": "xs",
                },
                # Progress Bar
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#DCE5D8",
                    "height": "8px",
                    "cornerRadius": "30px",
                    "margin": "sm",
                    "contents": bar_contents,
                },
                # Stats rows
                _stat_row("Attended days", str(summary.get("attended_days", 0)), margin="lg", label_flex=5, value_flex=2),
                _stat_row("Absences", str(summary.get("absent_days", 0)), value_color=absent_color, margin="sm", label_flex=5, value_flex=2),
                _stat_row("Half-days", str(summary.get("half_days", 0)), margin="sm", label_flex=5, value_flex=2),
                _stat_row("Late arrivals", str(summary.get("late_days", 0)), margin="sm", label_flex=5, value_flex=2),
                _stat_row("Remaining scheduled workdays", str(summary.get("remaining_scheduled_workdays", 0)), margin="sm", label_flex=5, value_flex=2),
                _stat_row("Today's status", str(summary.get("today_status", "Present")), margin="sm", label_flex=4, value_flex=3),
                # Action button
                _button(
                    "View Attendance History",
                    "action=richmenu_leave_history",
                    margin="xl",
                ),
            ],
        },
    }
    return FlexMessage(
        alt_text=f"My Attendance: {pct_str} ({month_label})",
        contents=FlexContainer.from_dict(bubble),
    )


# ======================================================================
# 3. Leave History (Exact Match for Image 4)
# ======================================================================

_LEAVE_EN_LABELS = {
    "病假": "Sick Leave",
    "事假": "Personal Leave",
    "經痛": "Menstrual Leave",
    "特休": "Annual Leave",
    "半天": "Half Day",
    "回菲律賓": "Abroad Leave",
    "待確認": "Pending Leave",
}


def leave_history_message(
    records: list[dict[str, str]],
    *,
    month_label: str,
) -> FlexMessage:
    """Build the Leave History card matching Image 4."""
    record_boxes: list[dict[str, object]] = []

    if records:
        for rec in records[:6]:
            cat_val = rec.get("type", "Leave")
            cat_en = _LEAVE_EN_LABELS.get(cat_val, cat_val)
            rec_date = rec.get("date", "")
            status_text = rec.get("status") or "Recorded"

            record_boxes.append(
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "md",
                    "paddingAll": "12px",
                    "margin": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "alignItems": "center",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": f"{cat_en}",
                                    "weight": "bold",
                                    "size": "sm",
                                    "color": DARK_GREEN,
                                    "flex": 1,
                                    "wrap": True,
                                },
                                _pill(status_text),
                            ],
                        },
                        {
                            "type": "text",
                            "text": f"{rec_date}",
                            "size": "xs",
                            "color": MUTED_TEXT,
                            "margin": "xs",
                        },
                    ],
                }
            )
    else:
        record_boxes.append(
            {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#FFFFFF",
                "cornerRadius": "md",
                "paddingAll": "14px",
                "margin": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": "No leave records found for this period.",
                        "size": "sm",
                        "color": MUTED_TEXT,
                        "align": "center",
                    }
                ],
            }
        )

    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "Leave History",
                    "weight": "bold",
                    "size": "xl",
                    "color": DARK_GREEN,
                },
                {
                    "type": "text",
                    "text": f"{month_label} · Sample records",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                *record_boxes,
                _button(
                    "Request a Correction",
                    "action=ticket_prompt&category=Attendance Correction",
                    margin="xl",
                ),
            ],
        },
    }
    return FlexMessage(
        alt_text=f"Leave History ({month_label})",
        contents=FlexContainer.from_dict(bubble),
    )


# ======================================================================
# 4. Work Schedule
# ======================================================================

def work_schedule_message(
    schedule_days: list[dict[str, object]],
    *,
    title_label: str = "Upcoming Schedule",
) -> FlexMessage:
    """Build the Work Schedule card matching the portal design."""
    day_boxes: list[dict[str, object]] = []

    for day in schedule_days[:7]:
        is_work = day.get("is_workday", False)
        type_str = str(day.get("type", "Workday" if is_work else "Rest Day"))
        badge_bg = "#E2F0D9" if is_work else "#ECEEEA"
        badge_color = DARK_GREEN if is_work else MUTED_TEXT

        day_boxes.append(
            {
                "type": "box",
                "layout": "horizontal",
                "alignItems": "center",
                "backgroundColor": "#FFFFFF",
                "cornerRadius": "md",
                "paddingAll": "12px",
                "margin": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "flex": 1,
                        "contents": [
                            {
                                "type": "text",
                                "text": f"{day.get('date_str')} ({day.get('weekday_en')})",
                                "weight": "bold",
                                "size": "sm",
                                "color": DARK_GREEN,
                            },
                            {
                                "type": "text",
                                "text": str(day.get("note", "")),
                                "size": "xxs",
                                "color": MUTED_TEXT,
                                "margin": "xs",
                            },
                        ],
                    },
                    _pill(type_str, bg=badge_bg, color=badge_color),
                ],
            }
        )

    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "Work Schedule",
                    "weight": "bold",
                    "size": "xl",
                    "color": DARK_GREEN,
                },
                {
                    "type": "text",
                    "text": f"{title_label} · CSIE Work Calendar",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                *day_boxes,
                {
                    "type": "text",
                    "text": "Default schedule: Wednesday–Sunday (8 hrs/day). Synchronized with Google Sheets Work Calendar tab.",
                    "size": "xxs",
                    "color": MUTED_TEXT,
                    "wrap": True,
                    "margin": "md",
                },
                _button("Apply for Leave", "action=richmenu_leave_request", margin="md"),
            ],
        },
    }
    return FlexMessage(
        alt_text="Work Schedule · CSIE Student Portal",
        contents=FlexContainer.from_dict(bubble),
    )


# ======================================================================
# 5. Leave Request (請假申請)
# ======================================================================

def _leave_autofill_button(label: str, category: str, day) -> dict[str, object]:
    return {
        "type": "button", "style": "primary", "color": BUTTON_GREEN,
        "height": "sm", "margin": "sm",
        "action": {
            "type": "postback", "label": label,
            "data": f"action=request_leave_type&category={category}",
            "inputOption": "openKeyboard",
            "fillInText": f"Leave {day.isoformat()} {category} Reason: [your reason]",
        },
    }


def leave_request_menu_message(student_name: str | None = None) -> FlexMessage:
    """Build editable leave templates starting on the next scheduled workday."""
    from scheduler.work_calendar import is_workday
    template_day = datetime.now(ZoneInfo("Asia/Taipei")).date()
    while not is_workday(template_day):
        template_day += timedelta(days=1)
    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "Leave Request",
                    "weight": "bold",
                    "size": "xl",
                    "color": DARK_GREEN,
                },
                {
                    "type": "text",
                    "text": "Choose a category to fill your draft. Edit the date and reason, then send.",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "md",
                    "paddingAll": "14px",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "⚠️ Submission Notice",
                            "weight": "bold",
                            "size": "sm",
                            "color": DARK_GREEN,
                        },
                        {
                            "type": "text",
                            "text": (
                                "Requests are flagged for administrator review. "
                                "Submission does not automatically imply HR approval."
                            ),
                            "size": "xs",
                            "color": MUTED_TEXT,
                            "wrap": True,
                            "margin": "xs",
                        },
                    ],
                },
                _leave_autofill_button("🤒 Sick Leave", "Sick Leave", template_day),
                _leave_autofill_button("📋 Personal Leave", "Personal Leave", template_day),
                _leave_autofill_button("🌸 Menstrual Leave", "Menstrual Leave", template_day),
                _leave_autofill_button("🏖️ Annual Leave", "Annual Leave", template_day),
                _leave_autofill_button("⏱️ Half-day Leave", "Half Day", template_day),
                {
                    "type": "text",
                    "text": "Leave YYYY-MM-DD <Type> Reason: <your reason>\nLeave can only be filed on scheduled workdays.",
                    "size": "xxs",
                    "color": MUTED_TEXT,
                    "align": "center",
                    "wrap": True,
                    "margin": "md",
                },
            ],
        },
    }
    return FlexMessage(
        alt_text="Leave Request · CSIE Student Portal",
        contents=FlexContainer.from_dict(bubble),
    )


# ======================================================================
# 6. Help Center (服務中心)
# ======================================================================

def help_center_message(tickets: list[dict[str, str]] | None = None) -> FlexMessage:
    """Build the Help Center support desk card."""
    ticket_boxes: list[dict[str, object]] = []
    if tickets:
        for t in tickets[:3]:
            t_id = t.get("Ticket ID", "")
            t_status = t.get("Status", "OPEN")
            t_msg = t.get("Message", "")
            badge_bg = "#FFF2CC" if t_status.upper() == "OPEN" else "#E2F0D9"
            badge_color = "#8A6D1C" if t_status.upper() == "OPEN" else DARK_GREEN

            ticket_boxes.append(
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "md",
                    "paddingAll": "12px",
                    "margin": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "alignItems": "center",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": f"Ticket #{t_id}",
                                    "weight": "bold",
                                    "size": "sm",
                                    "color": DARK_GREEN,
                                    "flex": 1,
                                },
                                _pill(t_status, bg=badge_bg, color=badge_color),
                            ],
                        },
                        {
                            "type": "text",
                            "text": t_msg[:60],
                            "size": "xs",
                            "color": MUTED_TEXT,
                            "wrap": True,
                            "margin": "xs",
                        },
                    ],
                }
            )

    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "Help Center",
                    "weight": "bold",
                    "size": "xl",
                    "color": DARK_GREEN,
                },
                {
                    "type": "text",
                    "text": "Service Desk & Correction Tickets",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "md",
                    "paddingAll": "14px",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "Need assistance?",
                            "weight": "bold",
                            "size": "sm",
                            "color": DARK_GREEN,
                        },
                        {
                            "type": "text",
                            "text": (
                                "Submit a ticket for incorrect attendance, missing leave records, "
                                "or salary questions. Admins will review and respond."
                            ),
                            "size": "xs",
                            "color": MUTED_TEXT,
                            "wrap": True,
                            "margin": "xs",
                        },
                    ],
                },
                *ticket_boxes,
                _button("✏️ Attendance Correction", "action=ticket_prompt&category=Attendance Correction", margin="sm"),
                _button("💰 Salary Discrepancy", "action=ticket_prompt&category=Salary Discrepancy", margin="sm"),
                _button("📄 Missing Leave Record", "action=ticket_prompt&category=Missing Leave Record", margin="sm"),
                _button("❓ Help & Support", "action=ticket_prompt&category=General Inquiry", margin="sm"),
                {
                    "type": "text",
                    "text": "Direct ticket: send /ticket <message>",
                    "size": "xxs",
                    "color": MUTED_TEXT,
                    "align": "center",
                    "wrap": True,
                    "margin": "md",
                },
            ],
        },
    }
    return FlexMessage(
        alt_text="Help Center · CSIE Student Portal",
        contents=FlexContainer.from_dict(bubble),
    )


# ======================================================================
# 7. Welcome & Initialization Cards in Same Design
# ======================================================================

def welcome_message(
    student: dict[str, object] | None = None,
    *,
    display_name: str | None = None,
) -> FlexMessage:
    """Build the welcome portal card shown for /hello matching the design."""
    student_name = ""
    student_id = ""
    if student:
        student_name = str(student.get("chinese_name") or student.get("name") or "").strip()
        student_id = str(student.get("student_id") or "").strip()

    is_recognized = bool(student_name and student_id)
    badge_label = "Connected" if is_recognized else "Guest"
    badge_bg = "#D7F2E9" if is_recognized else BADGE_BG
    badge_color = "#176B5B" if is_recognized else BADGE_TEXT

    welcome_title = f"Welcome, {student_name}!" if is_recognized else "Welcome to CSIE Attendance"

    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "alignItems": "center",
                    "contents": [
                        {
                            "type": "text",
                            "text": "CSIE Student",
                            "wrap": True,
                            "weight": "bold",
                            "size": "xl",
                            "color": DARK_GREEN,
                            "flex": 1,
                        },
                        _pill(badge_label, bg=badge_bg, color=badge_color),
                    ],
                },
                {
                    "type": "text",
                    "text": "Attendance & Work Services",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "md",
                    "paddingAll": "14px",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": welcome_title,
                            "weight": "bold",
                            "size": "sm",
                            "color": DARK_GREEN,
                        },
                        {
                            "type": "text",
                            "text": (
                                "Track your attendance, view estimated salary, check work schedules, "
                                "and submit leave notices using the portal menu below."
                            ),
                            "size": "xs",
                            "color": MUTED_TEXT,
                            "wrap": True,
                            "margin": "xs",
                        },
                        *(
                            [
                                {"type": "separator", "color": DIVIDER_COLOR, "margin": "sm"},
                                _stat_row("Student Name", student_name, margin="sm", label_flex=4, value_flex=4),
                                _stat_row("Student ID", student_id, margin="xs", label_flex=4, value_flex=4),
                                _stat_row("Status", "Connected & Active", margin="xs", label_flex=4, value_flex=4),
                            ]
                            if is_recognized
                            else []
                        ),
                    ],
                },
                _button("My Attendance", "action=richmenu_attendance", margin="sm"),
                _button("Salary Inquiry", "action=richmenu_salary", margin="xs"),
                _button("Terms & Usage", "action=view_terms", margin="xs"),
                _button("Change Language", "action=language_settings", margin="xs"),
            ],
        },
    }

    return FlexMessage(
        alt_text="CSIE Student Portal: Attendance & Work Services",
        contents=FlexContainer.from_dict(bubble),
        quick_reply=QuickReply(
            items=[
                QuickReplyItem(action=PostbackAction(label="My Attendance", data="action=richmenu_attendance", display_text="My Attendance")),
                QuickReplyItem(action=PostbackAction(label="Salary Inquiry", data="action=richmenu_salary", display_text="Salary Inquiry")),
                QuickReplyItem(action=PostbackAction(label="Terms & Usage", data="action=view_terms", display_text="Terms & Usage")),
                QuickReplyItem(action=PostbackAction(label="Change Language", data="action=language_settings", display_text="Change Language")),
            ]
        ),
    )


def initialization_message(
    student: dict[str, object] | None = None,
    *,
    display_name: str | None = None,
    is_registered: bool = False,
    error_status: str | None = None,
) -> FlexMessage:
    """Build the English initialization card with terms and student recognition."""
    student_name = ""
    student_id = ""
    if student:
        student_name = str(student.get("chinese_name") or student.get("name") or "").strip()
        student_id = str(student.get("student_id") or "").strip()

    is_recognized = bool(student_name and student_id)
    failure_details = {
        "ambiguous": (
            "More than one active student record matches your LINE name.",
            "Ask an administrator to correct the duplicate LINE Display Name entries, then message the bot again.",
            "Duplicate Names",
        ),
        "conflict": (
            "The matching student record is already linked to a different LINE account.",
            "Ask an administrator to check the existing account link.",
            "Account Conflict",
        ),
        "profile_unavailable": (
            "We could not retrieve your LINE profile name.",
            "Try again in a private chat. If this continues, contact an administrator.",
            "Profile Unavailable",
        ),
    }
    failure_reason, failure_steps, failure_label = failure_details.get(error_status, (
        "Your LINE profile name does not match an active student record.",
        f'Ask an administrator to set LINE Display Name in your Students row to "{display_name or "your current LINE profile name"}". '
        "Alternatively, change your LINE profile name to match the sheet. Then message the bot again. "
        "Authorization links a matching record; it does not approve a name mismatch.",
        "Name Not Matched",
    ))
    badge_label = "Recognized" if is_recognized else failure_label if error_status in failure_details else "Unmatched"
    badge_bg = "#D7F2E9" if is_recognized else "#FCE8E6"
    badge_color = "#176B5B" if is_recognized else DEDUCTION_RED

    body_contents = [
        {
            "type": "box", "layout": "horizontal", "alignItems": "center",
            "contents": [
                {"type": "text", "text": "CSIE Student", "weight": "bold", "size": "lg", "color": DARK_GREEN, "flex": 1, "wrap": True},
                _pill(badge_label, bg=badge_bg, color=badge_color),
            ],
        },
        {"type": "text", "text": "Welcome to CSIE Attendance Bot.", "size": "sm", "color": DARK_GREEN, "wrap": True, "margin": "md"},
    ]
    if is_recognized:
        body_contents.extend([
            _stat_row("Student Name", student_name, margin="md"),
            _stat_row("Student ID", student_id, margin="xs"),
            _stat_row("LINE Name", display_name or student_name, margin="xs"),
        ])
    else:
        body_contents.extend([
            _stat_row("LINE Name", display_name or "Unknown", margin="md"),
            _stat_row("Status", failure_label, margin="xs", value_color=DEDUCTION_RED),
            {"type": "text", "text": failure_reason, "size": "xs", "color": MUTED_TEXT, "wrap": True, "margin": "sm"},
            {"type": "text", "text": failure_steps, "size": "xxs", "color": LABEL_TEXT, "wrap": True, "margin": "xs"},
        ])
    body_contents.extend([
        {"type": "separator", "color": DIVIDER_COLOR, "margin": "md"},
        {"type": "text", "text": "Review the Terms & Usage for details about this service and how your information is used.", "size": "xs", "color": MUTED_TEXT, "wrap": True, "margin": "sm"},
    ])
    if not is_recognized:
        body_contents.append(_button("Contact Admin / Support", "action=richmenu_help", margin="sm"))
    bubble = {
        "type": "bubble", "size": "mega",
        "body": {"type": "box", "layout": "vertical", "backgroundColor": CARD_BG, "paddingAll": "16px", "contents": body_contents},
        "footer": {"type": "box", "layout": "vertical", "backgroundColor": CARD_BG, "spacing": "sm", "paddingAll": "16px", "contents": [
            _button("Terms & Usage", "action=view_terms", color=BUTTON_GREEN, margin="none"),
            _button("Start Using", "action=start_using", color=BUTTON_GREEN, margin="8px"),
        ]},
    }
    return FlexMessage(
        alt_text=f"CSIE Student: Account Initialization ({'Recognized' if is_recognized else 'Unmatched'})",
        contents=FlexContainer.from_dict(bubble),
    )


def terms_of_use_message() -> FlexMessage:
    """Display the complete supplied policy in separate, readable bubbles."""
    policy = (Path(__file__).resolve().parent.parent / "assets" / "terms.md").read_text()
    paragraphs = []
    for paragraph in policy.split("\n\n"):
        paragraph = re.sub(r"^#{1,6}\s*", "", paragraph.strip(), flags=re.MULTILINE)
        paragraph = paragraph.replace("**", "").replace("*", "")
        if paragraph and paragraph != "---":
            paragraphs.extend(paragraph[index:index + 1400] for index in range(0, len(paragraph), 1400))
    pages = [[]]
    count = 0
    for paragraph in paragraphs:
        if count + len(paragraph) > 2200 and pages[-1]:
            pages.append([])
            count = 0
        pages[-1].append(paragraph)
        count += len(paragraph)
    bubbles = []
    for index, page in enumerate(pages):
        bubble = {
            "type": "bubble", "size": "mega",
            "body": {"type": "box", "layout": "vertical", "backgroundColor": CARD_BG, "paddingAll": "16px", "contents": [
                {"type": "text", "text": f"Terms & Usage · {index + 1}/{len(pages)}", "weight": "bold", "size": "md", "color": DARK_GREEN, "wrap": True},
                *[{"type": "text", "text": paragraph, "size": "xs", "color": LABEL_TEXT, "wrap": True, "margin": "md"} for paragraph in page],
            ]},
        }
        bubbles.append(bubble)
    return FlexMessage(alt_text="CSIE Attendance Bot: Terms & Usage", contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles}))


def terms_agreement_confirmed_message(
    student: dict[str, object],
) -> FlexMessage:
    """Build the confirmation card when a user agrees to the terms of usage."""
    student_name = str(student.get("chinese_name") or student.get("name") or "").strip()
    student_id = str(student.get("student_id") or "").strip()

    bubble: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": CARD_BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "alignItems": "center",
                    "contents": [
                        {
                            "type": "text",
                            "text": "CSIE Student",
                            "wrap": True,
                            "weight": "bold",
                            "size": "xl",
                            "color": DARK_GREEN,
                            "flex": 1,
                        },
                        _pill("Active", bg="#D7F2E9", color="#176B5B"),
                    ],
                },
                {
                    "type": "text",
                    "text": "Authorization Saved · Terms Accepted",
                    "size": "xs",
                    "color": MUTED_TEXT,
                    "margin": "xs",
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "md",
                    "paddingAll": "14px",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "Setup Complete!",
                            "weight": "bold",
                            "size": "sm",
                            "color": DARK_GREEN,
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Welcome, {student_name}! Your account authorization and acceptance of the terms have been saved. "
                                "Your LINE account is fully connected and recognized in the CSIE Attendance database."
                            ),
                            "size": "xs",
                            "color": MUTED_TEXT,
                            "wrap": True,
                            "margin": "xs",
                        },
                        {"type": "separator", "color": DIVIDER_COLOR, "margin": "sm"},
                        _stat_row("Student Name", student_name, margin="sm", label_flex=4, value_flex=4),
                        _stat_row("Student ID", student_id, margin="xs", label_flex=4, value_flex=4),
                        _stat_row("Status", "Verified & Connected", margin="xs", label_flex=4, value_flex=4),
                    ],
                },
                _button("My Attendance", "action=richmenu_attendance", margin="sm"),
                _button("Salary Inquiry", "action=richmenu_salary", margin="xs"),
                _button("Terms & Usage", "action=view_terms", margin="xs"),
                _button("Change Language", "action=language_settings", margin="xs"),
            ],
        },
    }

    return FlexMessage(
        alt_text="CSIE Student Portal: Terms Accepted & Account Active",
        contents=FlexContainer.from_dict(bubble),
        quick_reply=QuickReply(
            items=[
                QuickReplyItem(action=PostbackAction(label="My Attendance", data="action=richmenu_attendance", display_text="My Attendance")),
                QuickReplyItem(action=PostbackAction(label="Salary Inquiry", data="action=richmenu_salary", display_text="Salary Inquiry")),
                QuickReplyItem(action=PostbackAction(label="Terms & Usage", data="action=view_terms", display_text="Terms & Usage")),
                QuickReplyItem(action=PostbackAction(label="Change Language", data="action=language_settings", display_text="Change Language")),
            ]
        ),
    )


def language_settings_message() -> FlexMessage:
    return FlexMessage(
        alt_text="Language / 語言",
        contents=FlexContainer.from_dict({
            "type": "bubble", "body": {
                "type": "box", "layout": "vertical", "backgroundColor": CARD_BG,
                "contents": [
                    {"type": "text", "text": "Language / 語言", "weight": "bold", "wrap": True},
                    _button("English", "action=set_language&language=en", margin="md"),
                    _button("繁體中文", "action=set_language&language=zh-TW", margin="md"),
                ],
            },
        }),
    )


def response_card_message(text: str) -> FlexMessage:
    """Format plain responses as readable cards, preserving all supplied text."""
    title = "Invalid Leave" if "Leave can only be filed on a scheduled workday." in text else "CSIE Student"
    sections = []
    for paragraph in text.split("\n\n"):
        if paragraph:
            sections.extend(paragraph[index:index + 1400] for index in range(0, len(paragraph), 1400))
    pages = [[]]
    length = 0
    for section in sections:
        if length + len(section) > 2800 and pages[-1]:
            pages.append([])
            length = 0
        pages[-1].append(section)
        length += len(section)
    bubbles = [{
        "type": "bubble", "size": "mega",
        "body": {"type": "box", "layout": "vertical", "backgroundColor": CARD_BG, "paddingAll": "16px", "contents": [
            {"type": "text", "text": title, "weight": "bold", "size": "lg", "color": DARK_GREEN, "wrap": True},
            {"type": "separator", "color": DIVIDER_COLOR, "margin": "sm"},
            *[{"type": "text", "text": section, "size": "sm", "color": LABEL_TEXT, "wrap": True, "margin": "md"} for section in page],
        ]},
    } for page in pages]
    contents = bubbles[0] if len(bubbles) == 1 else {"type": "carousel", "contents": bubbles}
    return FlexMessage(alt_text=title + ": " + (text[:280] or "Notification"), contents=FlexContainer.from_dict(contents))


def portal_menu_message() -> FlexMessage:
    """Persistent in-chat navigation for clients without a rich menu."""
    return FlexMessage(alt_text="CSIE Student: Portal Menu", contents=FlexContainer.from_dict({
        "type": "bubble", "size": "mega",
        "body": {"type": "box", "layout": "vertical", "backgroundColor": CARD_BG, "paddingAll": "16px", "contents": [
            {"type": "text", "text": "CSIE Student", "weight": "bold", "size": "lg", "color": DARK_GREEN, "wrap": True},
            {"type": "text", "text": "Portal Menu", "size": "sm", "color": MUTED_TEXT, "margin": "xs"},
            *[_button(label, f"action={action}", margin="sm") for label, action in [
                ("My Attendance", "richmenu_attendance"), ("Salary Inquiry", "richmenu_salary"), ("Terms & Usage", "view_terms"),
                ("Change Language", "language_settings"),
            ]],
        ]},
    }))
