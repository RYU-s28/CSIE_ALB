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
from bot.search_context import begin_search, clear_search

STATUSES = {
    "present": ("Present / Remove Leave", "出席"),
    "sick": ("Sick Leave", "病假"), "personal": ("Personal Leave", "事假"),
    "menstrual": ("Menstrual Leave", "經痛"), "annual": ("Annual Leave · Paid", "特休"),
    "half": ("Half Day", "半天"), "late": ("Late", "遲到"),
    "exam": ("考試 · Personal Leave", "事假"), "pending": ("Pending Review", "待確認"),
    "clear": ("Clear · Blank Record", ""),
    "absent": ("Absent", "不出來"),
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
        spaced_buttons = [{**button, "margin": "none" if index == 0 else "8px"} for index, button in enumerate(buttons)]
        bubble["footer"] = {"type": "box", "layout": "vertical", "backgroundColor": CARD_BG, "paddingAll": "16px", "contents": spaced_buttons}
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
        _button("Salary Inquiry", "action=richmenu_salary", margin="none"),
        _button("Terms & Usage", "action=view_terms", margin="none"),
        _button("Change Language", "action=language_settings", margin="none"),
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
        _button("Edit Leave", action("admin_students", date=day), margin="none"),
        date_button("admin_attendance" , day),
    ], subtitle=day.isoformat())


def daily_report_message(day, page=0):
    """Preview the current group report privately without issuing or saving it."""
    from bot.commands import _records_for_date
    from attendance.report import build_report
    students, expected = db.get_report_students()
    return build_report(report_date=day, total_students=expected,
                        expected_students=expected, students=students,
                        records=_records_for_date(day))


def search_button(day, *, query="", bus=False):
    return {"type": "button", "style": "secondary", "height": "sm", "action": {
        "type": "postback", "label": "🔎 Search name or student ID",
        "data": action("admin_timeout_bus_search" if bus else "admin_search", date=day),
        "inputOption": "openKeyboard",
    }}


def search_query(query):
    query = (query or "").strip()
    if len(urlencode({"query": query})) > 150:
        raise ValueError("Search using a shorter name or student ID.")
    return query


def students_message(day, page=0, query=None):
    query = search_query(query)
    search = search_button(day, query=query)
    navigation = [search, date_button("admin_students", day), _button("Back to Status", action("admin_attendance", date=day), margin="none")]
    if not query:
        return card("Find Student", [paragraph("Tap Search, enter a student ID or any part of their Chinese, English, or LINE name, then send.")], navigation, subtitle=day.isoformat())
    matches = db.search_active_students(query)
    page_size = 5
    page = min(max(0, page), max(0, (len(matches) - 1) // page_size))
    buttons = [search]
    buttons.extend(_button(f"{student['student_id']} · {student.get('chinese_name') or student.get('name') or student.get('full_name')}"[:40], action("admin_student", student=student["student_id"], date=day), margin="none") for student in matches[page * page_size:(page + 1) * page_size])
    if page:
        buttons.append(_button("Previous Matches", action("admin_students", page=page - 1, date=day, query=query), margin="none"))
    if (page + 1) * page_size < len(matches):
        buttons.append(_button("More Matches", action("admin_students", page=page + 1, date=day, query=query), margin="none"))
    buttons.append(_button("Back to Status", action("admin_attendance", date=day), margin="none"))
    return card("Search Results", [paragraph(f'{len(matches)} match(es) for "{query}". Choose a student.' if matches else f'No students matched "{query}". Try another name or ID.')], buttons, subtitle=f"{day.isoformat()} · Page {page + 1}")


def student_message(student, day, ticket_id=None):
    entries = db.get_monthly_report_entries(str(student["student_id"]), day)
    name = str(student.get("chinese_name") or student["name"])
    cancel = action("admin_ticket", ticket=ticket_id) if ticket_id else action("admin_students", date=day)
    if day not in entries:
        return card("Choose a Workday", [_stat_row("Student Name", name, margin="md"), paragraph("This date is not scheduled. Choose the attendance date to continue.")], [date_button("admin_student", day, student=student["student_id"], ticket=ticket_id), _button("Back", cancel, margin="none")], subtitle=day.isoformat())
    current = entries[day] or ("Present" if day < today() else "Pending")
    short_labels = {"present": "Present", "sick": "Sick Leave", "personal": "Personal", "menstrual": "Menstrual", "annual": "Annual · Paid", "half": "Half Day", "late": "Late", "exam": "考試", "pending": "Pending", "clear": "Clear"}
    choices = []
    for key in STATUSES:
        if key == "absent":
            continue
        button = _button(short_labels[key], action("admin_change", student=student["student_id"], date=day, status=key, ticket=ticket_id), margin="none")
        if key == "clear":
            button["color"] = DEDUCTION_RED
        button["flex"] = 1
        button["adjustMode"] = "shrink-to-fit"
        choices.append(button)
    grid = []
    for offset in range(0, len(choices), 2):
        pair = choices[offset:offset + 2]
        if len(pair) == 1:
            pair.append({"type": "box", "layout": "vertical", "flex": 1, "contents": []})
        pair[1] = {**pair[1], "margin": "8px"}
        grid.append({"type": "box", "layout": "horizontal", "margin": "8px", "contents": pair})
    return card("Edit Attendance", [
        _stat_row("Student Name", name, margin="md"),
        _stat_row("Student ID", str(student["student_id"]), margin="xs"),
        _stat_row("Current Status", current, margin="xs"),
        paragraph("Tap a status to save immediately. Present records attendance. Clear removes the saved record and blanks the report cell. Annual leave is paid."),
        *grid,
    ], [date_button("admin_student", day, student=student["student_id"], ticket=ticket_id), _button("Back to Ticket" if ticket_id else "Find Another Student", cancel, margin="none")], subtitle=day.isoformat())


def edit_shortcut(message, actor):
    """Open editing directly for a unique name or ID; never guess an identity."""
    from bot.commands import is_admin_user
    if not is_admin_user(actor):
        raise ValueError("Attendance editing is available to administrators only.")
    clear_search(actor)
    match = re.fullmatch(r"\s*/?edit(?:\s+(.*))?\s*", message, flags=re.IGNORECASE)
    query = (match.group(1) or "").strip() if match else ""
    if not query:
        return card("Edit Attendance", [paragraph("Send Edit followed by a name or student ID. Examples: Edit S06677; Edit 杜榮瑪 sick leave; Edit 10/14 S06677 clear.")])
    explicit_day = None
    # Dates may precede or follow the identity; month/day uses the Taipei year.
    date_match = re.search(r"(?:^|\s)(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})(?=\s|$)", query)
    if date_match:
        value = date_match[1]
        explicit_day = (date.fromisoformat(value) if "-" in value else
                        date(today().year, *map(int, value.split("/"))))
        query = (query[:date_match.start()] + " " + query[date_match.end():]).strip()
    status_key = None
    aliases = {key: key for key in STATUSES}
    aliases.update({"sick leave": "sick", "personal leave": "personal",
                    "menstrual leave": "menstrual", "annual leave": "annual",
                    "half day": "half", "pending review": "pending", "考試": "exam", "absent": "absent"})
    for label in sorted(aliases, key=len, reverse=True):
        status_match = re.search(r"\s+" + re.escape(label) + r"$", query, re.IGNORECASE)
        if status_match:
            status_key = aliases[label]
            query = query[:status_match.start()].strip()
            break
    query = query.strip('"\'')
    if not query:
        raise ValueError("Include a student name or ID after Edit.")
    student = db.find_student_by_id(query)
    if not student:
        matches = db.search_active_students(search_query(query))
        if len(matches) != 1:
            return students_message(explicit_day or today(), query=query)
        student = matches[0]
    day = explicit_day or today()
    if explicit_day is None:
        entries = db.get_monthly_report_entries(str(student["student_id"]), day)
        if day not in entries:
            future_days = sorted(value for value in entries if value > day)
            if future_days:
                day = future_days[0]
    if status_key is not None:
        from urllib.parse import parse_qs
        from attendance.leave_message import validate_leave_workday
        status = STATUSES[status_key][1]
        if status_key != "clear" and status not in {"出席", "遲到"}:
            validate_leave_workday(day)
        snapshot, _ = _snapshot(str(student["student_id"]), day, None)
        data = parse_qs(signed_action(actor, "admin_apply", student=student["student_id"],
                                     date=day, status=status_key, snapshot=snapshot))
        return handle_postback(data, actor)
    return student_message(student, day)


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
    if status_key != "clear" and status not in {"出席", "遲到"}:
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
    if name not in {"admin_search", "admin_timeout_bus_search"}:
        clear_search(actor)
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
        begin_search(actor, day)
        return card("Search Students", [paragraph("Type a student name or ID in the typing area and send. Search is active for five minutes.")], [_button("Cancel Search", action("admin_students", date=day), margin="none")], subtitle=day.isoformat())
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
    if name in {"admin_change", "admin_preview"}:
        # Old cards used admin_preview; they now also save on the first tap.
        from urllib.parse import parse_qs
        from attendance.leave_message import validate_leave_workday
        status = STATUSES[status_key][1]
        if status_key != "clear" and status not in {"出席", "遲到"}:
            validate_leave_workday(day)
        snapshot, _ = _snapshot(str(student["student_id"]), day, ticket_id)
        immediate = signed_action(actor, "admin_apply", student=student["student_id"],
                                  date=day, status=status_key, ticket=ticket_id, snapshot=snapshot)
        return handle_postback(parse_qs(immediate), actor, notify=notify)
    if name == "admin_apply":
        verify_action(actor, data)
        snapshot, previous = _snapshot(str(student["student_id"]), day, ticket_id)
        if snapshot != get("snapshot"):
            raise ValueError("Attendance changed since this preview. Refresh and confirm the current record.")
        status = STATUSES[status_key][1]
        if status_key == "clear":
            result = db.clear_student_attendance(str(student["student_id"]), day, actor)
            if ticket_id:
                save_ticket_note(ticket_id, f"Attendance cleared for {day}. Audit: {result['action_id'] or 'already blank'}.")
            return card("Attendance Cleared", [_stat_row("Student ID", str(student["student_id"]), margin="md"), _stat_row("Date", day.isoformat(), margin="xs"), paragraph("Saved records were removed and the Monthly Report cell is blank.")], [_button("Back to Ticket", action("admin_ticket", ticket=ticket_id), margin="none")] if ticket_id else [_button("Edit This Student", action("admin_student", student=student["student_id"], date=day), margin="none")])
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
