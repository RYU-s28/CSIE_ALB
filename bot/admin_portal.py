"""Private administrator cards, ticket workflow, and audited attendance edits."""
from datetime import date, datetime, timedelta
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from linebot.v3.messaging import FlexContainer, FlexMessage
from bot.line_ui import CARD_BG, DARK_GREEN, LABEL_TEXT, MUTED_TEXT, DEDUCTION_RED, _button, _stat_row
from database import google_sheets as db

STATUSES = {
    "present": ("Present / Remove Leave", "出席"),
    "sick": ("Sick Leave", "病假"), "personal": ("Personal Leave", "事假"),
    "menstrual": ("Menstrual Leave", "經痛"), "annual": ("Annual Leave · Paid", "特休"),
    "half": ("Half Day", "半天"), "late": ("Late", "遲到"),
    "absent": ("Absent", "不出來"), "pending": ("Pending Review", "待確認"),
}


def today():
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


def action(name, **values):
    return urlencode({"action": name, **{key: value for key, value in values.items() if value is not None}})


def card(title, contents, buttons=(), subtitle=None):
    header = [{"type": "text", "text": title, "size": "lg", "weight": "bold", "color": DARK_GREEN, "wrap": True}]
    if subtitle:
        header.append({"type": "text", "text": subtitle, "size": "xs", "color": MUTED_TEXT, "wrap": True, "margin": "xs"})
    bubble = {"type": "bubble", "size": "mega", "body": {
        "type": "box", "layout": "vertical", "backgroundColor": CARD_BG,
        "paddingAll": "16px", "contents": header + list(contents),
    }}
    if buttons:
        bubble["footer"] = {"type": "box", "layout": "vertical", "backgroundColor": CARD_BG, "paddingAll": "16px", "spacing": "sm", "contents": list(buttons)}
    return FlexMessage(alt_text=f"CSIE Admin: {title}", contents=FlexContainer.from_dict(bubble))


def paragraph(text):
    return {"type": "text", "text": str(text) or "—", "size": "sm", "color": LABEL_TEXT, "wrap": True, "margin": "md"}


def date_button(name, day, **values):
    return {"type": "button", "style": "secondary", "height": "sm", "action": {
        "type": "datetimepicker", "label": "Choose Date", "mode": "date", "initial": day.isoformat(),
        "data": action(name, **values),
    }}


def portal_message():
    return card("Admin Portal", [paragraph("Manage student requests and attendance privately in LINE.")], [
        _button("My Attendance", "action=richmenu_attendance", margin="none"),
        _button("Leave History", "action=richmenu_leave_history", margin="none"),
        _button("Salary Inquiry", "action=richmenu_salary", margin="none"),
        _button("Time Out Report", "action=admin_timeout", margin="none"),
        _button("Attendance Status", "action=admin_attendance", margin="none"),
        _button("Help Center · Tickets", "action=admin_tickets", margin="none"),
    ], subtitle="Administrator workspace")


def tickets_message(page=0):
    tickets = db.get_open_tickets()
    page = min(max(0, page), max(0, (len(tickets) - 1) // 8))
    buttons = [_button(f"#{ticket['Ticket ID']} · {ticket['Student ID']}", action("admin_ticket", ticket=ticket["Ticket ID"]), margin="none") for ticket in tickets[page * 8:(page + 1) * 8]]
    if page:
        buttons.append(_button("Previous", action("admin_tickets", page=page - 1), margin="none"))
    if (page + 1) * 8 < len(tickets):
        buttons.append(_button("Next", action("admin_tickets", page=page + 1), margin="none"))
    buttons.extend([_button("Refresh Tickets", "action=admin_tickets", margin="none"), _button("Admin Portal", "action=admin_portal", margin="none")])
    return card("Help Center", [paragraph(f"{len(tickets)} open ticket(s). Select a request to review, correct attendance, or resolve it.")], buttons, subtitle=f"Tickets · Page {page + 1}")


def require_ticket(ticket_id):
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        raise ValueError("This ticket no longer exists. Refresh Help Center.")
    return ticket


def ticket_message(ticket):
    contents = [_stat_row("Student ID", ticket["Student ID"], margin="md"), _stat_row("Status", ticket["Status"], margin="xs")]
    student = db.find_student_by_id(ticket["Student ID"])
    if student:
        contents.append(_stat_row("Student Name", str(student.get("chinese_name") or student["name"]), margin="xs"))
    contents.extend(paragraph(ticket["Message"][index:index + 1400]) for index in range(0, len(ticket["Message"]), 1400))
    if ticket.get("Admin Note"):
        contents.append(paragraph("Resolution: " + ticket["Admin Note"]))
    ticket_id = ticket["Ticket ID"]
    buttons = []
    if ticket["Status"].upper() == "OPEN":
        buttons.extend([
            _button("Correct Student Attendance", action("admin_ticket_edit", ticket=ticket_id), margin="none"),
            _button("Resolve Ticket", action("admin_ticket_resolve", ticket=ticket_id), margin="none"),
        ])
    else:
        buttons.append(_button("Reopen Ticket", action("admin_ticket_reopen", ticket=ticket_id), margin="none"))
    buttons.append(_button("Back to Help Center", "action=admin_tickets", margin="none"))
    return card(f"Ticket #{ticket_id}", contents, buttons)


def attendance_message(day):
    rows = db.get_daily_monthly_report(day)
    present = half = absent = pending = annual = 0
    for row in rows:
        value = row["type"]
        if value == "特休":
            annual += 1
            present += 1
        elif value in {"出席", "遲到", "不坐公交車"} or (not value and day < today()):
            present += 1
        elif value == "半天":
            half += 1
        elif value in {"", "待確認", "Missing Report Row"}:
            pending += 1
        elif value != "Rest Day":
            absent += 1
    rest_day = bool(rows) and all(row["type"] == "Rest Day" for row in rows)
    return card("Attendance Status", [
        _stat_row("Day", "Rest Day" if rest_day else "Scheduled Workday", margin="md"),
        _stat_row("Students", str(len(rows)), margin="md"),
        _stat_row("Present / Paid Leave", str(present), margin="xs"),
        _stat_row("Annual Leave · Paid", str(annual), margin="xs"),
        _stat_row("Absences", str(absent), margin="xs"),
        _stat_row("Half Days", str(half), margin="xs"),
        _stat_row("Pending / Missing", str(pending), margin="xs"),
        paragraph("Monthly Report is the source. Blank today remains pending; past blank workdays count as present."),
    ], [
        _button("View Daily Report", action("admin_daily", date=day), margin="none"),
        _button("Add / Edit / Remove Leave", action("admin_students", date=day), margin="none"),
        date_button("admin_attendance" , day),
        _button("Refresh Status", action("admin_attendance", date=day), margin="none"),
        _button("Admin Portal", "action=admin_portal", margin="none"),
    ], subtitle=day.isoformat())


def daily_report_message(day, page=0):
    rows = db.get_daily_monthly_report(day)
    page = min(max(0, page), max(0, (len(rows) - 1) // 10))
    contents = []
    for row in rows[page * 10:(page + 1) * 10]:
        status = row["type"] or ("Present" if day < today() else "Pending" if day == today() else "Upcoming")
        contents.append(paragraph(f"{row['student_id']} · {row['name']}\n{status}"))
    buttons = [
        _button("Edit Attendance", action("admin_students", date=day), margin="none"),
        _button("Back to Status", action("admin_attendance", date=day), margin="none"),
    ]
    if page:
        buttons.append(_button("Previous Page", action("admin_daily", date=day, page=page - 1), margin="none"))
    if (page + 1) * 10 < len(rows):
        buttons.append(_button("Next Page", action("admin_daily", date=day, page=page + 1), margin="none"))
    return card("Daily Attendance Report", contents or [paragraph("No active students.")], buttons, subtitle=f"{day.isoformat()} · Page {page + 1}")


def students_message(day, page=0, query=None):
    students, _ = db.get_report_students()
    matches = [(sid, student) for sid, student in sorted(students.items()) if not query or query.casefold() in (sid + " " + student.display_name).casefold()]
    page = min(max(0, page), max(0, (len(matches) - 1) // 8))
    buttons = [_button(f"{sid} · {student.display_name}"[:40], action("admin_student", student=sid, date=day), margin="none") for sid, student in matches[page * 8:(page + 1) * 8]]
    if page:
        buttons.append(_button("Previous Students", action("admin_students", page=page - 1, date=day, query=query), margin="none"))
    if (page + 1) * 8 < len(matches):
        buttons.append(_button("Next Students", action("admin_students", page=page + 1, date=day, query=query), margin="none"))
    buttons.append({"type": "button", "style": "secondary", "action": {"type": "postback", "label": "Search Student", "data": action("admin_search", date=day), "inputOption": "openKeyboard", "fillInText": f"/adminfind {day.isoformat()} "}})
    buttons.append(_button("Back to Status", action("admin_attendance", date=day), margin="none"))
    return card("Choose Student", [paragraph("Select a student, then choose the attendance date and status.")], buttons, subtitle=f"{day.isoformat()} · {len(matches)} student(s) · Page {page + 1}")


def student_message(student, day, ticket_id=None):
    entries = db.get_monthly_report_entries(str(student["student_id"]), day)
    if day not in entries:
        raise ValueError("This date is not in the Monthly Report schedule. Choose a scheduled date.")
    current = entries[day] or ("Present" if day < today() else "Pending")
    buttons = [date_button("admin_student", day, student=student["student_id"], ticket=ticket_id)]
    buttons.extend(_button(label, action("admin_preview", student=student["student_id"], date=day, status=key, ticket=ticket_id), margin="none") for key, (label, value) in STATUSES.items())
    buttons.append(_button("Cancel", action("admin_ticket", ticket=ticket_id) if ticket_id else action("admin_attendance", date=day), margin="none"))
    return card("Edit Attendance", [
        _stat_row("Student Name", str(student.get("chinese_name") or student["name"]), margin="md"),
        _stat_row("Student ID", str(student["student_id"]), margin="xs"),
        _stat_row("Current Status", current, margin="xs"),
        paragraph("Present removes leave and restores attendance. Annual leave is paid. Changes require confirmation."),
    ], buttons, subtitle=day.isoformat())


def _snapshot(student_id, day, ticket_id):
    entries = db.get_monthly_report_entries(student_id, day)
    if day not in entries:
        raise ValueError("The selected date is not scheduled in the Monthly Report.")
    record = db.get_attendance_record(student_id, day)
    ticket = require_ticket(ticket_id) if ticket_id else None
    if ticket and (ticket["Student ID"] != student_id or ticket["Status"].upper() != "OPEN"):
        raise ValueError("This ticket is closed or belongs to a different student. Refresh Help Center.")
    state = {"grid": entries[day], "record": record, "ticket": ticket}
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16], entries[day]


def signed_action(actor, name, **values):
    values = {**values, "expires": int(time.time()) + 600}
    payload = action(name, **values)
    secret = os.getenv("LINE_CHANNEL_SECRET", "")
    if not secret:
        raise RuntimeError("LINE channel secret is required for confirmations.")
    digest = hmac.new(secret.encode(), (actor + "|" + payload).encode(), hashlib.sha256).hexdigest()[:24]
    return payload + "&token=" + digest


def verify_action(actor, data):
    values = {key: value[0] for key, value in data.items() if key != "token"}
    try:
        expires = int(values["expires"])
    except (KeyError, ValueError):
        raise ValueError("Invalid confirmation. Start again from the admin card.")
    expected = hmac.new(os.environ["LINE_CHANNEL_SECRET"].encode(), (actor + "|" + urlencode(values)).encode(), hashlib.sha256).hexdigest()[:24]
    if expires < time.time() or not hmac.compare_digest(expected, data.get("token", [""])[0]):
        raise ValueError("This confirmation expired or is invalid. Start again from the admin card.")


def preview_message(actor, student, day, status_key, ticket_id):
    from attendance.leave_message import validate_leave_workday
    status = STATUSES[status_key][1]
    if status not in {"出席", "遲到"}:
        validate_leave_workday(day)
    snapshot, previous = _snapshot(str(student["student_id"]), day, ticket_id)
    confirm = signed_action(actor, "admin_apply", student=student["student_id"], date=day, status=status_key, ticket=ticket_id, snapshot=snapshot)
    return card("Confirm Attendance Change", [
        _stat_row("Student Name", str(student.get("chinese_name") or student["name"]), margin="md"),
        _stat_row("Student ID", str(student["student_id"]), margin="xs"),
        _stat_row("Date", day.isoformat(), margin="xs"),
        _stat_row("Before", previous or "Blank", margin="xs"),
        _stat_row("After", STATUSES[status_key][0], margin="xs"),
        paragraph("Updates Attendance and Monthly Report with an audit entry. " + ("The ticket stays open until you resolve it." if ticket_id else "")),
    ], [_button("Confirm Change", confirm, color=DEDUCTION_RED, margin="none"), _button("Cancel", action("admin_student", student=student["student_id"], date=day, ticket=ticket_id), margin="none")])


def handle_postback(data, actor, params=None, notify=None):
    """Handle only admin actions; authorize every view and every mutation."""
    from bot.commands import is_admin_user
    if not is_admin_user(actor):
        raise ValueError("This workspace is available to administrators only.")
    get = lambda key, default="": data.get(key, [default])[0]
    name = get("action")
    selected = (params or {}).get("date") or get("date") or today().isoformat()
    day = date.fromisoformat(selected)
    ticket_id = get("ticket") or None
    if name.startswith("admin_timeout"):
        from bot.time_out_portal import handle_time_out
        return handle_time_out(data, actor, day)
    if name == "admin_portal":
        return portal_message()
    if name == "admin_tickets":
        return tickets_message(int(get("page", "0")))
    if name == "admin_ticket":
        return ticket_message(require_ticket(ticket_id))
    if name in {"admin_ticket_edit", "admin_ticket_resolve", "admin_ticket_reopen"}:
        ticket = require_ticket(ticket_id)
        if name == "admin_ticket_edit":
            student = db.find_student_by_id(ticket["Student ID"])
            if not student:
                raise ValueError("Student record not found. Correct the roster first.")
            match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", ticket["Message"])
            edit_day = date.fromisoformat(match[0]) if match else today()
            # A ticket may mention a rest day; let the admin choose another date.
            return card("Choose Correction Date", [paragraph(f"Ticket #{ticket_id} · {student['student_id']}\nChoose the date of the attendance correction.")], [date_button("admin_student", edit_day, student=student["student_id"], ticket=ticket_id), _button("Use Today", action("admin_student", student=student["student_id"], date=today(), ticket=ticket_id), margin="none")])
        close = name == "admin_ticket_resolve"
        confirm = signed_action(actor, "admin_ticket_commit", ticket=ticket_id, close=int(close), snapshot=hashlib.sha256(json.dumps(ticket, sort_keys=True).encode()).hexdigest()[:16])
        return card("Resolve Ticket" if close else "Reopen Ticket", [paragraph(f"Ticket #{ticket_id} · {ticket['Student ID']}\n" + ("Mark this request resolved after completing the requested correction." if close else "Return this request to the open queue."))], [_button("Confirm Resolve" if close else "Confirm Reopen", confirm, margin="none"), _button("Cancel", action("admin_ticket", ticket=ticket_id), margin="none")])
    if name == "admin_ticket_commit":
        verify_action(actor, data)
        ticket = require_ticket(ticket_id)
        snapshot = hashlib.sha256(json.dumps(ticket, sort_keys=True).encode()).hexdigest()[:16]
        if snapshot != get("snapshot"):
            raise ValueError("This ticket changed since you opened it. Refresh Help Center.")
        close = get("close") == "1"
        if not db.update_ticket(ticket_id, actor, close=close, note=ticket.get("Admin Note") or "Resolved through Admin Help Center."):
            raise RuntimeError("Ticket could not be updated.")
        if notify and ticket.get("LINE User ID"):
            notify(ticket["LINE User ID"], f"Your ticket #{ticket_id} was {'resolved' if close else 'reopened'} by an administrator.\n\n{ticket.get('Admin Note') or 'Contact Help Center if you still need assistance.'}")
        return ticket_message(require_ticket(ticket_id))
    if name == "admin_attendance":
        return attendance_message(day)
    if name == "admin_daily":
        return daily_report_message(day, int(get("page", "0")))
    if name == "admin_students":
        return students_message(day, int(get("page", "0")), get("query") or None)
    if name == "admin_search":
        return card("Search Students", [paragraph(f"Type /adminfind {day.isoformat()} followed by a student ID or name, then send.")])
    student = db.find_student_by_id(get("student"))
    if not student:
        raise ValueError("Student not found or name is ambiguous.")
    if ticket_id and require_ticket(ticket_id)["Student ID"] != str(student["student_id"]):
        raise ValueError("This ticket belongs to a different student.")
    if name == "admin_student":
        return student_message(student, day, ticket_id)
    status_key = get("status")
    if status_key not in STATUSES:
        raise ValueError("Unsupported attendance status.")
    if name == "admin_preview":
        return preview_message(actor, student, day, status_key, ticket_id)
    if name == "admin_apply":
        verify_action(actor, data)
        snapshot, previous = _snapshot(str(student["student_id"]), day, ticket_id)
        if snapshot != get("snapshot"):
            raise ValueError("Attendance changed since this preview. Refresh and confirm the current record.")
        status = STATUSES[status_key][1]
        if previous == status:
            return card("Already Up to Date", [paragraph("This status is already saved. No duplicate change was made.")], [_button("Back to Ticket", action("admin_ticket", ticket=ticket_id), margin="none")] if ticket_id else [_button("Back to Status", action("admin_attendance", date=day), margin="none")])
        result = db.upsert_attendance_record(str(student["student_id"]), str(student.get("chinese_name") or student["name"]), day, status, actor, raw_message="Admin Portal correction", audit_details=f"Admin Portal; ticket={ticket_id or 'manual'}")
        if not db.update_monthly_report_cell(str(student["student_id"]), day, status):
            raise RuntimeError("The attendance log was saved, but Monthly Report could not be updated. Retry the correction before resolving the ticket.")
        if ticket_id:
            # Keep the request open while recording the correction for resolution.
            save_ticket_note(ticket_id, f"Attendance corrected for {day}: {previous or 'Blank'} → {status}. Audit: {result['action_id']}.")
        return card("Attendance Updated", [_stat_row("Student ID", str(student["student_id"]), margin="md"), _stat_row("Date", day.isoformat(), margin="xs"), _stat_row("Status", status, margin="xs"), paragraph("Attendance, Monthly Report, and the audit log are saved.")], [_button("Back to Ticket", action("admin_ticket", ticket=ticket_id), margin="none")] if ticket_id else [_button("Back to Status", action("admin_attendance", date=day), margin="none")])
    raise ValueError("Unknown administrator action.")


def save_ticket_note(ticket_id, note):
    sheet = db._ensure_named_sheet("Tickets", db.TICKET_HEADERS)
    if sheet is None:
        raise RuntimeError("Ticket note could not be saved. Refresh the ticket before resolving it.")
    for index, row in enumerate(sheet.get_all_values()[1:], start=2):
        if row and row[0].casefold() == ticket_id.casefold():
            sheet.update(range_name=f"I{index}", values=[[note]], value_input_option="RAW")
            return
    raise ValueError("Ticket no longer exists.")
