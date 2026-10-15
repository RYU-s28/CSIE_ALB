"""Daily attendance, separate outbound/return transport, and school return reports."""
from datetime import date, datetime
import hashlib
import json
import re
import threading
from zoneinfo import ZoneInfo

from attendance.attendance import AttendanceRecord
from attendance.report import ABSENT_STATUSES, DailyReportText, build_report
from database import google_sheets as db

MORNING_HEADERS = ["Date", "Captured At", "Report", "Snapshot"]
DRAFT_HEADERS = ["Date", "Bus Overrides"]
RETURN_HEADERS = ["Date", "Returned", "Expected Return", "Report", "Confirmed At", "Confirmed By", "Everyone Returned"]


_bus_lock = threading.RLock()


def bus_choices(day):
    _, _, draft = _read_row("Time Out Drafts", DRAFT_HEADERS, day)
    values = json.loads(draft[1]) if draft and draft[1] else {}
    # Existing selections are return-trip choices; never move them to morning.
    if "morning" not in values and "afternoon" not in values:
        return {"morning": {}, "afternoon": values}
    return {trip: values.get(trip, {}) for trip in ("morning", "afternoon")}


def _eligible_roster(records, students):
    latest = {record.student_id: record for record in records}
    return {sid for sid in students if sid not in latest or (
        latest[sid].status not in ABSENT_STATUSES | {"special_leave"}
        and not (latest[sid].status == "unknown" and latest[sid].attendance_intent))}


def _without_bus_sections(report):
    kept, skipping = [], False
    for line in str(report).splitlines():
        if re.fullmatch(r"\s*不坐公交車(?:（上班）|（下班）)?[：:]\s*\d+人\s*", line):
            skipping = True
            continue
        if skipping:
            if not line.strip() or line.lstrip().startswith("@"):
                continue
            skipping = False
        if not re.match(r"^\s*回到學校[：:]", line):
            kept.append(line)
    return "\n".join(kept).rstrip()


def _bus_section(report, trip, ids, names):
    if not ids:
        return report
    label = "上班" if trip == "morning" else "下班"
    return report + f"\n\n不坐公交車（{label}）：{len(ids)}人" + "".join(f"\n@{names[sid]}" for sid in sorted(ids))


def apply_morning_bus(day, report, records, students):
    eligible = _eligible_roster(records, students)
    selected = {sid for sid, excluded in bus_choices(day)["morning"].items() if excluded is True and sid in eligible}
    return DailyReportText(_bus_section(_without_bus_sections(report), "morning", selected,
                                       {sid: student.line_label for sid, student in students.items()}))


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
    report = apply_morning_bus(day, report, records, students)
    return save_morning(day, report, records, students, expected)


def current_daily_snapshot(day):
    """Build return eligibility and report text from today's fresh grid only."""
    from attendance.report import records_from_monthly_report
    students, expected = db.get_report_students()
    records = records_from_monthly_report(day, students)
    latest = {record.student_id: record for record in records}
    roster = {}
    for sid, student in students.items():
        record = latest.get(sid)
        status = record.status if record else "present"
        absent = status in ABSENT_STATUSES or (status == "unknown" and record.attendance_intent)
        roster[sid] = {"name": student.line_label, "status": status,
                       "return_expected": not absent and status != "special_leave"}
    report = build_report(report_date=day, total_students=expected, expected_students=expected,
                          students=students, records=records)
    attended = expected - sum(student["status"] in ABSENT_STATUSES or student["status"] == "unknown"
                              for student in roster.values())
    return {"report": str(report), "snapshot": {"students": roster, "expected": expected,
                                                "attended": max(0, attended)}, "source": "Monthly Report"}


def get_state(day):
    morning = current_daily_snapshot(day)
    roster = morning["snapshot"]["students"]
    eligible = {sid for sid, student in roster.items() if student["return_expected"]}
    choices = bus_choices(day)
    overrides = choices["afternoon"]
    no_bus = {sid for sid, excluded in overrides.items() if excluded is True and sid in eligible}
    morning_no_bus = {sid for sid, excluded in choices["morning"].items() if excluded is True and sid in eligible}
    names = {sid: student["name"] for sid, student in roster.items()}
    morning["report"] = _bus_section(_without_bus_sections(morning["report"]), "morning", morning_no_bus, names)
    _, _, final = _read_row("Time Out Reports", RETURN_HEADERS, day)
    state = {"morning": morning, "eligible": sorted(eligible), "no_bus": sorted(no_bus), "overrides": overrides, "morning_overrides": choices["morning"], "morning_no_bus": sorted(morning_no_bus), "final": final}
    state["expected_return"] = len(eligible - no_bus)
    state["fingerprint"] = hashlib.sha256(json.dumps(state, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return state


def set_bus_exception(day, student_id, excluded, trip="afternoon"):
    if trip not in {"morning", "afternoon"}:
        raise ValueError("Choose morning or afternoon bus.")
    with _bus_lock:
        state = get_state(day)
        if not state or student_id not in state["eligible"]:
            raise ValueError("Choose a student attending in the Monthly Report for this date.")
        choices = bus_choices(day)
        choices[trip][student_id] = bool(excluded)
        sheet, index, _ = _read_row("Time Out Drafts", DRAFT_HEADERS, day)
        values = [day.isoformat(), json.dumps(choices, ensure_ascii=False)]
        if index:
            sheet.update(range_name=f"A{index}:B{index}", values=[values], value_input_option="RAW")
        else:
            sheet.append_row(values, value_input_option="RAW")


def compose_report(state, returned):
    if returned < 0 or returned > state["expected_return"]:
        raise ValueError(f"Returned count must be between 0 and {state['expected_return']}.")
    report = _without_bus_sections(state["morning"]["report"])
    names = {sid: student["name"] for sid, student in state["morning"]["snapshot"]["students"].items()}
    report = _bus_section(report, "morning", state.get("morning_no_bus", []), names)
    report = _bus_section(report, "afternoon", state["no_bus"], names)
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
