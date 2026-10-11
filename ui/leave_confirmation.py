"""Flex messages for saved attendance records and withdrawal confirmation."""

from __future__ import annotations

from linebot.v3.messaging import (
    FlexContainer,
    FlexMessage,
    PostbackAction,
)

CARD_BG = "#F1F5E9"
DARK_GREEN = "#1E421E"
BUTTON_GREEN = "#264E22"
MUTED_TEXT = "#6E7D6E"
LABEL_TEXT = "#556555"
DIVIDER_COLOR = "#D6DDD2"
BADGE_BG = "#E2E8DC"
BADGE_TEXT = "#304030"

_CATEGORY_LABELS = {
    "病假": "Sick Leave",
    "事假": "Personal Leave",
    "經痛": "Menstrual Leave",
    "特休": "Annual Leave",
    "半天": "Half Day",
    "回菲律賓": "Abroad",
    "待確認": "Pending Review",
}


def _pill(text: str, *, bg: str = BADGE_BG, color: str = BADGE_TEXT) -> dict[str, object]:
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": bg,
        "cornerRadius": "xxl",
        "paddingStart": "8px",
        "paddingEnd": "8px",
        "paddingTop": "2px",
        "paddingBottom": "2px",
        "contents": [
            {
                "type": "text",
                "text": text,
                "size": "xs",
                "color": color,
                "weight": "bold",
                "align": "center",
            }
        ],
    }


def leave_confirmation_message(
    *,
    student_name: str,
    leave_date: str,
    category: str,
    record_id: str,
    confirmed: bool = True,
    withdrawable: bool = True,
) -> FlexMessage:
    """Build a post-save card matching the CSIE Student Portal design."""

    category_label = _CATEGORY_LABELS.get(category, category)
    heading = "Leave Recorded" if confirmed else "Leave Needs Review"
    badge_label = "Recorded" if confirmed else "Pending"
    footer_note = (
        "Automatically classified. If anything is incorrect, request a correction "
        "from an administrator."
        if confirmed
        else "Your absence notice was recorded as 待確認. Please contact an "
        "administrator to confirm the leave type."
    )

    contents: dict[str, object] = {
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
                    "contents": [
                        {
                            "type": "text",
                            "text": heading,
                            "weight": "bold",
                            "size": "xl",
                            "color": DARK_GREEN,
                            "flex": 4,
                        },
                        _pill(badge_label),
                    ],
                },
                {
                    "type": "text",
                    "text": "CSIE Attendance · Shu-Te 3",
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
                        _detail("Student", student_name),
                        _detail("Date", leave_date),
                        _detail("Leave category", f"{category} · {category_label}"),
                        _detail("Record ID", record_id),
                    ],
                },
                {
                    "type": "text",
                    "text": footer_note,
                    "size": "xxs",
                    "color": MUTED_TEXT,
                    "wrap": True,
                    "margin": "sm",
                },
                _button(
                    "Request Correction",
                    f"action=correction&record_id={record_id}",
                    style="primary",
                    color=BUTTON_GREEN,
                    margin="md",
                ),
                *(
                    [
                        _button(
                            "Withdraw This Leave",
                            f"action=withdraw&record_id={record_id}",
                            style="secondary",
                            margin="sm",
                        )
                    ]
                    if withdrawable
                    else []
                ),
                {
                    "type": "text",
                    "text": "CSIE Attendance Assistant · Automated record",
                    "size": "xxs",
                    "color": MUTED_TEXT,
                    "align": "center",
                    "margin": "md",
                },
            ],
        },
    }
    return FlexMessage(
        alt_text=f"{heading}: {category} on {leave_date}",
        contents=FlexContainer.from_dict(contents),
    )


def withdrawal_confirmation_message(
    *,
    category: str,
    leave_date: str,
    record_id: str,
    confirmation_data: str,
) -> FlexMessage:
    """Ask the student to confirm withdrawing this exact record."""

    bubble = {
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
                    "text": "Withdraw this leave?",
                    "weight": "bold",
                    "size": "xl",
                    "color": DARK_GREEN,
                },
                {
                    "type": "text",
                    "text": "This action cannot be undone here.",
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
                        _detail("Category", category),
                        _detail("Date", leave_date),
                        _detail("Record ID", record_id),
                    ],
                },
                _button(
                    "Confirm Withdrawal",
                    confirmation_data,
                    style="primary",
                    color="#B42318",
                    margin="md",
                ),
                _button(
                    "Keep This Leave",
                    f"action=cancel_withdraw&record_id={record_id}",
                    style="secondary",
                    margin="sm",
                ),
            ],
        },
    }
    return FlexMessage(
        alt_text=f"Confirm withdrawal of {category} on {leave_date}",
        contents=FlexContainer.from_dict(bubble),
    )


def attendance_status_message(
    *,
    category: str,
    leave_date: str,
    record_id: str,
) -> FlexMessage:
    """Build a compact personal status card for one attendance record."""

    bubble = {
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
                    "text": "Attendance Record",
                    "weight": "bold",
                    "size": "xl",
                    "color": DARK_GREEN,
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "md",
                    "paddingAll": "14px",
                    "margin": "md",
                    "contents": [
                        _detail("Date", leave_date),
                        _detail("Status", category),
                        _detail("Record ID", record_id),
                    ],
                },
            ],
        },
    }
    return FlexMessage(
        alt_text=f"Attendance status: {category} on {leave_date}",
        contents=FlexContainer.from_dict(bubble),
    )


def _detail(label: str, value: str) -> dict[str, object]:
    return {
        "type": "box",
        "layout": "horizontal",
        "margin": "xs",
        "contents": [
            {
                "type": "text",
                "text": label,
                "size": "sm",
                "color": LABEL_TEXT,
                "flex": 4,
                "wrap": True,
            },
            {
                "type": "text",
                "text": value,
                "size": "sm",
                "color": DARK_GREEN,
                "weight": "bold",
                "align": "end",
                "flex": 5,
                "wrap": True,
            },
        ],
    }


def _button(
    label: str,
    data: str,
    *,
    style: str = "secondary",
    color: str | None = None,
    margin: str = "sm",
) -> dict[str, object]:
    button_action = PostbackAction(label=label, data=data)
    button: dict[str, object] = {
        "type": "button",
        "style": style,
        "height": "sm",
        "margin": margin,
        "action": button_action.to_dict(),
    }
    if color:
        button["color"] = color
    return button
