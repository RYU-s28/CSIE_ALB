"""Admin-only bus exception selection and confirmed plain-text return reports."""
from attendance.report import DailyReportText, GroupReportText
from attendance import time_out
from bot.admin_portal import action, card, date_button, paragraph, signed_action, verify_action, today
from bot.line_ui import DEDUCTION_RED, _button, _stat_row


def timeout_message(day):
    state = time_out.get_state(day)
    if state is None:
        return card("Time Out Report", [
            paragraph("No saved morning report exists for this date. The scheduled morning report and /report save one automatically."),
            paragraph("Save Current Morning Report captures the current attendance records; it cannot recover an earlier report that was never saved."),
        ], [
            _button("Save Current Morning Report", action("admin_timeout_capture", date=day), margin="none"),
            date_button("admin_timeout", day),
            _button("Admin Portal", "action=admin_portal", margin="none"),
        ], subtitle=day.isoformat())
    snapshot = state["morning"]["snapshot"]
    final = state["final"]
    returned = int(final[1]) if final else None
    complete = returned == state["expected_return"] if returned is not None else False
    current_report = False
    if final and returned is not None and 0 <= returned <= state["expected_return"]:
        current_report = final[3] == str(time_out.compose_report(state, returned))
    contents = [
        _stat_row("Morning Expected", str(snapshot["expected"]), margin="md"),
        _stat_row("Morning Attended", str(snapshot["attended"]), margin="xs"),
        _stat_row("No Bus", str(len(state["no_bus"])), margin="xs"),
        _stat_row("Expected School Return", str(state["expected_return"]), margin="xs"),
        _stat_row("Confirmed Returned", str(returned) if returned is not None else "Not Confirmed", margin="xs"),
        _stat_row("Status", "Everyone Returned" if complete and current_report else "Refresh Confirmation" if final and not current_report else "Awaiting Return Confirmation", margin="xs"),
        paragraph("Check the no-bus list, then confirm how many actually returned. The morning attendance totals and leave list are preserved. Paid annual leave is not a bus passenger."),
    ]
    return card("Time Out Report", contents, [
        _button("View Saved Morning Report", action("admin_timeout_morning", date=day), margin="none"),
        _button("Choose Who Won't Take Bus", action("admin_timeout_bus", date=day), margin="none"),
        _button("Preview Everyone Returned", action("admin_timeout_preview", date=day), margin="none"),
        {"type": "button", "style": "secondary", "action": {"type": "postback", "label": "Enter Actual Return Count", "data": action("admin_timeout_count", date=day), "inputOption": "openKeyboard", "fillInText": f"/timeout {day.isoformat()} "}},
        date_button("admin_timeout", day),
        _button("Refresh Return Status", action("admin_timeout", date=day), margin="none"),
        _button("Admin Portal", "action=admin_portal", margin="none"),
    ], subtitle=day.isoformat())


def bus_message(day, page=0):
    state = time_out.get_state(day)
    if state is None:
        return timeout_message(day)
    candidates = state["eligible"]
    page = min(max(0, page), max(0, (len(candidates) - 1) // 8))
    roster = state["morning"]["snapshot"]["students"]
    buttons = []
    for sid in candidates[page * 8:(page + 1) * 8]:
        excluded = sid in state["no_bus"]
        label = ("✓ No Bus · " if excluded else "Bus · ") + roster[sid]["name"]
        buttons.append(_button(label[:40], action("admin_timeout_set_bus", date=day, student=sid, excluded=int(not excluded), page=page), margin="none"))
    if page:
        buttons.append(_button("Previous Students", action("admin_timeout_bus", date=day, page=page - 1), margin="none"))
    if (page + 1) * 8 < len(candidates):
        buttons.append(_button("Next Students", action("admin_timeout_bus", date=day, page=page + 1), margin="none"))
    buttons.append(_button("Done · Back to Time Out", action("admin_timeout", date=day), margin="none"))
    return card("No-Bus List", [paragraph("Tap an attendee to mark or clear No Bus. These transport choices do not reduce attendance or salary."), _stat_row("No Bus", str(len(state["no_bus"])), margin="md"), _stat_row("Expected Return", str(state["expected_return"]), margin="xs")], buttons, subtitle=f"{day.isoformat()} · Page {page + 1}")


def preview_message(day, actor, returned=None):
    state = time_out.get_state(day)
    if state is None:
        return timeout_message(day)
    returned = state["expected_return"] if returned is None else returned
    time_out.compose_report(state, returned)  # Validate the number before issuing confirmation.
    complete = returned == state["expected_return"]
    confirm = signed_action(actor, "admin_timeout_confirm", date=day, returned=returned, snapshot=state["fingerprint"])
    return card("Confirm Time Out Report", [
        _stat_row("Morning Attended", str(state["morning"]["snapshot"]["attended"]), margin="md"),
        _stat_row("No Bus", str(len(state["no_bus"])), margin="xs"),
        _stat_row("Expected Return", str(state["expected_return"]), margin="xs"),
        _stat_row("回到學校", str(returned), margin="xs"),
        paragraph("Confirm only after checking that everyone listed for the bus has returned to school." if complete else f"{state['expected_return'] - returned} expected passenger(s) have not yet been confirmed returned. This report will remain incomplete."),
        paragraph("The confirmed report will be posted as plain text to the configured group chat, with the morning leave list and 回到學校 appended."),
    ], [
        _button("Confirm Everyone Returned" if complete else "Confirm Partial Return", confirm, color=DEDUCTION_RED, margin="none"),
        _button("Cancel", action("admin_timeout", date=day), margin="none"),
    ], subtitle=day.isoformat())


def handle_time_out(data, actor, day):
    from bot.commands import is_admin_user
    if not is_admin_user(actor):
        raise ValueError("Time Out Report is available to administrators only.")
    get = lambda key, default="": data.get(key, [default])[0]
    name = get("action")
    if name == "admin_timeout":
        return timeout_message(day)
    if name == "admin_timeout_capture":
        if day > today():
            raise ValueError("A morning report cannot be captured for a future day.")
        from scheduler.work_calendar import is_workday
        if not is_workday(day):
            raise ValueError("This is a rest day. There is no bus return report to capture.")
        return GroupReportText(time_out.capture_current_morning(day)["report"])
    if name == "admin_timeout_morning":
        state = time_out.get_state(day)
        return DailyReportText(state["morning"]["report"]) if state else timeout_message(day)
    if name == "admin_timeout_bus":
        return bus_message(day, int(get("page", "0")))
    if name == "admin_timeout_set_bus":
        time_out.set_bus_exception(day, get("student"), get("excluded") == "1")
        return bus_message(day, int(get("page", "0")))
    if name == "admin_timeout_count":
        return card("Enter Return Count", [paragraph(f"Send /timeout {day.isoformat()} followed by the number who actually returned. For example: /timeout {day.isoformat()} 22")])
    if name == "admin_timeout_preview":
        raw = get("returned")
        return preview_message(day, actor, int(raw) if raw else None)
    if name == "admin_timeout_confirm":
        verify_action(actor, data)
        return GroupReportText(time_out.confirm_return(day, int(get("returned")), actor, get("snapshot")))
    raise ValueError("Unknown Time Out Report action.")
