"""LINE Flex message templates for the student-facing interface."""

from decimal import Decimal

from linebot.v3.messaging import (
    FlexContainer,
    FlexMessage,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
)

from attendance.salary import SalaryEstimate


def welcome_message() -> FlexMessage:
    """Build the welcome card shown for explicit hello/help requests."""

    return FlexMessage(
        alt_text="CSIE Attendance Assistant: welcome and student options",
        contents=FlexContainer.from_dict(
            {
                "type": "bubble",
                "size": "kilo",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#176B5B",
                    "paddingAll": "20px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "CSIE Attendance Bot",
                            "weight": "bold",
                            "color": "#FFFFFF",
                            "size": "xl",
                        },
                        {
                            "type": "text",
                            "text": "Student attendance assistant",
                            "color": "#D7F2E9",
                            "size": "sm",
                            "margin": "sm",
                        },
                    ],
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "md",
                    "paddingAll": "20px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "Welcome to CSIE Attendance",
                            "weight": "bold",
                            "size": "md",
                            "wrap": True,
                        },
                        {
                            "type": "text",
                            "text": (
                                "I help track leave notifications submitted "
                                "in this LINE chat."
                            ),
                            "size": "sm",
                            "color": "#5B6470",
                            "wrap": True,
                        },
                        {
                            "type": "separator",
                            "margin": "sm",
                        },
                        {
                            "type": "text",
                            "text": "What I can help with",
                            "weight": "bold",
                            "size": "sm",
                            "margin": "sm",
                        },
                        {
                            "type": "text",
                            "text": (
                                "• Recognize leave notifications automatically\n"
                                "• Check your attendance status\n"
                                "• Check your estimated salary\n"
                                "• Send a request to an administrator"
                            ),
                            "size": "sm",
                            "color": "#5B6470",
                            "wrap": True,
                        },
                    ],
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "paddingAll": "16px",
                    "contents": [
                        {
                            "type": "text",
                            "text": (
                                "Personal attendance and salary details are "
                                "only shown in a private chat."
                            ),
                            "size": "xs",
                            "color": "#78828D",
                            "wrap": True,
                        },
                    ],
                },
            }
        ),
        quick_reply=QuickReply(
            items=[
                QuickReplyItem(
                    action=PostbackAction(
                        label="My Status",
                        data="action=statusme",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="Salary",
                        data="action=salary",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="Help",
                        data="action=help",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="Contact Admin",
                        data="action=contact",
                    )
                ),
            ]
        ),
    )


def salary_inquiry_message(
    estimate: SalaryEstimate,
    *,
    month_label: str,
) -> FlexMessage:
    """Build a private salary estimate card using the existing bot design."""

    def amount(value: Decimal) -> str:
        return f"NT${value:,.2f}"

    def detail_row(
        label: str,
        value: str,
        *,
        bold: bool = False,
    ) -> dict[str, object]:
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": label,
                    "size": "sm",
                    "color": "#5B6470",
                    "flex": 3,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": value,
                    "size": "sm",
                    "color": "#303840",
                    "weight": "bold" if bold else "regular",
                    "align": "end",
                    "flex": 2,
                    "wrap": True,
                },
            ],
        }

    return FlexMessage(
        alt_text=f"Estimated salary for {month_label}",
        contents=FlexContainer.from_dict(
            {
                "type": "bubble",
                "size": "kilo",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#176B5B",
                    "paddingAll": "20px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "Salary Estimate",
                            "weight": "bold",
                            "color": "#FFFFFF",
                            "size": "xl",
                        },
                        {
                            "type": "text",
                            "text": month_label,
                            "color": "#D7F2E9",
                            "size": "sm",
                            "margin": "sm",
                        },
                    ],
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "md",
                    "paddingAll": "20px",
                    "contents": [
                        {
                            "type": "text",
                            "text": (
                                f"Attendance: {estimate.full_days} full days, "
                                f"{estimate.half_days} half days "
                                f"({estimate.total_hours} hours)"
                            ),
                            "size": "sm",
                            "color": "#5B6470",
                            "wrap": True,
                        },
                        {
                            "type": "text",
                            "text": "Earnings",
                            "weight": "bold",
                            "size": "sm",
                            "margin": "sm",
                        },
                        detail_row(
                            "Gross salary (NT$196/hour)",
                            amount(estimate.gross_salary),
                        ),
                        {
                            "type": "separator",
                            "margin": "sm",
                        },
                        {
                            "type": "text",
                            "text": "Deductions",
                            "weight": "bold",
                            "size": "sm",
                            "margin": "sm",
                        },
                        detail_row("Welfare fund (0.5%)", amount(estimate.welfare_fund)),
                        detail_row("Labor insurance", amount(estimate.labor_insurance)),
                        detail_row("Health insurance", amount(estimate.health_insurance)),
                        detail_row("Income tax (5%)", amount(estimate.income_tax)),
                        detail_row(
                            "Total deductions",
                            amount(estimate.total_deductions),
                        ),
                        {
                            "type": "separator",
                            "margin": "sm",
                        },
                        detail_row(
                            "Take-home estimate",
                            amount(estimate.net_salary),
                            bold=True,
                        ),
                    ],
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "paddingAll": "16px",
                    "contents": [
                        {
                            "type": "text",
                            "text": (
                                "*Salary is an estimate and may have a few "
                                "differences based on meal deductions and "
                                "personal deductions."
                            ),
                            "size": "xs",
                            "color": "#78828D",
                            "wrap": True,
                        },
                    ],
                },
            }
        ),
    )
