"""Flex messages for saved attendance records and withdrawal confirmation."""

from __future__ import annotations

from linebot.v3.messaging import (
    FlexContainer,
    FlexMessage,
    PostbackAction,
)


_CATEGORY_LABELS = {
    "病假": "Sick Leave",
    "事假": "Personal Leave",
    "經痛": "Menstrual Leave",
    "特休": "Annual Leave",
    "半天": "Half Day",
    "回菲律賓": "Abroad",
    "待確認": "Pending Review",
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
    """Build a post-save card; callbacks carry only the persisted record ID."""

    category_label = _CATEGORY_LABELS.get(category, category)
    heading = "Leave Recorded" if confirmed else "Leave Needs Review"
    status = "Confirmed" if confirmed else "Pending"
    color = "#137A58" if confirmed else "#A96900"
    footer_note = (
        "Automatically classified. If anything is incorrect, request a review "
        "from an administrator."
        if confirmed
        else "Your absence notice was recorded as 待確認. Please contact an "
        "administrator to confirm the leave type."
    )
    contents: dict[str, object] = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": color,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "CSIE ATTENDANCE · SHU-TE 3",
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "sm",
                },
                {
                    "type": "text",
                    "text": heading,
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "md",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": (
                        "Your attendance notification was saved."
                        if confirmed
                        else "Your notification was saved for administrator review."
                    ),
                    "color": "#E4F5EC",
                    "size": "sm",
                    "wrap": True,
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": f"RECORD STATUS  ·  {status.upper()}",
                    "color": color,
                    "weight": "bold",
                    "size": "sm",
                },
                _detail("Student", student_name),
                _detail("Date", leave_date),
                _detail("Leave category", f"{category} · {category_label}"),
                _detail("Record ID", record_id),
                {"type": "separator", "margin": "xl"},
                {
                    "type": "text",
                    "text": footer_note,
                    "size": "xs",
                    "color": "#718078",
                    "wrap": True,
                    "margin": "xl",
                },
            ],
        },
        "footer": _footer(record_id, withdrawable=withdrawable),
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
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "Withdraw this leave?",
                    "weight": "bold",
                    "size": "xl",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": (
                        f"{category} · {leave_date}\nRecord {record_id}\n\n"
                        "This action removes only this record and cannot be undone here."
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
            "spacing": "sm",
            "paddingAll": "15px",
            "contents": [
                _button(
                    "Confirm Withdrawal",
                    confirmation_data,
                    style="primary",
                    color="#B42318",
                ),
                _button(
                    "Keep This Leave",
                    f"action=cancel_withdraw&record_id={record_id}",
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
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#176B5B",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "MY ATTENDANCE",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "size": "lg",
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "20px",
            "contents": [
                _detail("Date", leave_date),
                _detail("Status", category),
                _detail("Record ID", record_id),
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
        "layout": "baseline",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": label,
                "size": "sm",
                "color": "#78828D",
                "flex": 3,
                "wrap": True,
            },
            {
                "type": "text",
                "text": value,
                "size": "sm",
                "color": "#26332E",
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
) -> dict[str, object]:
    button_action = PostbackAction(label=label, data=data)
    button: dict[str, object] = {
        "type": "button",
        "style": style,
        "height": "sm",
        "action": button_action.to_dict(),
    }
    if color:
        button["color"] = color
    return button


def _footer(record_id: str, *, withdrawable: bool) -> dict[str, object]:
    buttons = [
        _button(
            "View My Status",
            f"action=status&record_id={record_id}",
            style="primary",
        ),
        _button(
            "Request Correction",
            f"action=correction&record_id={record_id}",
        ),
    ]
    if withdrawable:
        buttons.append(
            _button(
                "Withdraw This Leave",
                f"action=withdraw&record_id={record_id}",
            )
        )
    buttons.append(
        {
            "type": "text",
            "text": "CSIE Attendance Assistant · Automated record",
            "size": "xxs",
            "color": "#8A938E",
            "align": "center",
            "wrap": True,
            "margin": "md",
        }
    )
    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "paddingAll": "15px",
        "contents": buttons,
    }
