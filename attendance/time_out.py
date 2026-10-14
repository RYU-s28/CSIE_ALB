"""Immutable morning reports and administrator-confirmed school return reports."""
from datetime import date, datetime
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from attendance.attendance import AttendanceRecord
from attendance.report import ABSENT_STATUSES, DailyReportText, build_report
from database import google_sheets as db

MORNING_HEADERS = ["Date", "Captured At", "Report", "Snapshot"]
DRAFT_HEADERS = ["Date", "Bus Overrides"]
RETURN_HEADERS = ["Date", "Returned", "Expected Return", "Report", "Confirmed At", "Confirmed By", "Everyone Returned"]


def _read_row(tab, headers, day):
    sheet = db._ensure_named_sheet(tab, headers)
    if sheet is None:
        raise RuntimeError(f"{tab} worksheet is unavailable.")
    for index, row in enumerate(sheet.get_all_values()[1:], start=2):
        if row and row[0] == day.isoformat():
            return sheet, index, row + [""] * max(0, len(headers) - len(row))
    return sheet, None, None


def get_morning(day):
    _, _, row = _read_row("Morning Reports", MORNING_HEADERS, day)
    if row is None:
        return None
    return {"report": row[2], "snapshot": json.loads(row[3]), "captured_at": row[1]}


def save_morning(day, report, records, students, expected):
    """Freeze the first issued morning report; later leave changes cannot replace it."""
    from scheduler.work_calendar import is_workday
    if day > datetime.now(ZoneInfo("Asia/Taipei")).date() or not is_workday(day):
        return None
    existing = get_morning(day)
    if existing:
        return existing
    latest = {record.student_id: record for record in records}
    roster = {}
    for sid, student in students.items():
        record = latest.get(sid)
        status = record.status if record else "present"
        absent = status in ABSENT_STATUSES or (status == "unknown" and record.attendance_intent)
        roster[sid] = {
            "name": student.line_label, "status": status,
            # Paid annual leave preserves attendance/pay but does not imply a bus passenger.
            "return_expected": not absent and status != "special_leave",
        }
    match = re.search(r"實到人數[：:]\s*(\d+)", report)
    snapshot = {"students": roster, "expected": expected, "attended": int(match[1]) if match else 0}
    sheet, _, _ = _read_row("Morning Reports", MORNING_HEADERS, day)
    captured = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    sheet.append_row([day.isoformat(), captured, str(report), json.dumps(snapshot, ensure_ascii=False)], value_input_option="RAW")
    return {"report": str(report), "snapshot": snapshot, "captured_at": captured}


def capture_current_morning(day):
    existing = get_morning(day)
    if existing:
        return existing
    from attendance.report import records_from_monthly_report
    students, expected = db.get_report_students()
    records = records_from_monthly_report(day, students)
    report = build_report(report_date=day, total_students=expected, expected_students=expected, students=students, records=records)
    return save_morning(day, report, records, students, expected)


def get_state(day):
    morning = get_morning(day)
    if morning is None:
        return None
    roster = morning["snapshot"]["students"]
    eligible = {sid for sid, student in roster.items() if student["return_expected"]}
    current = {row["student_id"] for row in db.get_attendance_rows(day) if row.get("type") == "不坐公交車"}
    no_bus = (current | {sid for sid, student in roster.items() if student["status"] == "no_bus"}) & eligible
    _, _, draft = _read_row("Time Out Drafts", DRAFT_HEADERS, day)
    overrides = json.loads(draft[1]) if draft else {}
    for sid, excluded in overrides.items():
        if sid in eligible:
            if excluded:
                no_bus.add(sid)
            else:
                no_bus.discard(sid)
    _, _, final = _read_row("Time Out Reports", RETURN_HEADERS, day)
    state = {"morning": morning, "eligible": sorted(eligible), "no_bus": sorted(no_bus), "overrides": overrides, "final": final}
    state["expected_return"] = len(eligible - no_bus)
    state["fingerprint"] = hashlib.sha256(json.dumps(state, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return state


def set_bus_exception(day, student_id, excluded):
    state = get_state(day)
    if not state or student_id not in state["eligible"]:
        raise ValueError("Choose a student who attended in the saved morning report.")
    overrides = {**state["overrides"], student_id: bool(excluded)}
    sheet, index, _ = _read_row("Time Out Drafts", DRAFT_HEADERS, day)
    values = [day.isoformat(), json.dumps(overrides, ensure_ascii=False)]
    if index:
        sheet.update(range_name=f"A{index}:B{index}", values=[values], value_input_option="RAW")
    else:
        sheet.append_row(values, value_input_option="RAW")


def compose_report(state, returned):
    if returned < 0 or returned > state["expected_return"]:
        raise ValueError(f"Returned count must be between 0 and {state['expected_return']}.")
    # Retain the morning report verbatim except for the transport exception section.
    lines = state["morning"]["report"].splitlines()
    kept = []
    skipping = False
    for line in lines:
        if re.fullmatch(r"\s*不坐公交車[：:]\s*\d+人\s*", line):
            skipping = True
            continue
        if skipping:
            if not line.strip() or line.lstrip().startswith("@"):
                continue
            skipping = False
        if not re.match(r"^\s*回到學校[：:]", line):
            kept.append(line)
    report = "\n".join(kept).rstrip()
    if state["no_bus"]:
        roster = state["morning"]["snapshot"]["students"]
        report += f"\n\n不坐公交車：{len(state['no_bus'])}人"
        report += "".join(f"\n@{roster[sid]['name']}" for sid in state["no_bus"])
    return DailyReportText(report + f"\n\n回到學校：{returned}")


def confirm_return(day, returned, actor, fingerprint):
    from bot.commands import is_admin_user
    if not is_admin_user(actor):
        raise ValueError("Only administrators can confirm time out reports.")
    state = get_state(day)
    if state is None or state["fingerprint"] != fingerprint:
        raise ValueError("Bus selections or this report changed. Refresh Time Out Report and confirm again.")
    report = compose_report(state, returned)
    sheet, index, _ = _read_row("Time Out Reports", RETURN_HEADERS, day)
    values = [day.isoformat(), returned, state["expected_return"], str(report), datetime.now(ZoneInfo("Asia/Taipei")).isoformat(), actor, returned == state["expected_return"]]
    if index:
        sheet.update(range_name=f"A{index}:G{index}", values=[values], value_input_option="RAW")
    else:
        sheet.append_row(values, value_input_option="RAW")
    return report
