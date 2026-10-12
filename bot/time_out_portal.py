"""Admin-only bus exception selection and confirmed plain-text return reports."""
from attendance.report import DailyReportText, GroupReportText
from attendance import time_out
from bot.search_context import begin_search
from bot.admin_portal import action, card, paragraph, verify_action, today, search_button, search_query
from bot.line_ui import _button, _stat_row


def timeout_message(day):
    state = time_out.get_state(day)
    if state is None:
        return card("Time Out Report", [paragraph("No saved morning report exists for this date. Save the current report first; an earlier report that was never saved cannot be recovered.")], [
            _button("Save Current Morning Report", action("admin_timeout_capture", date=day), margin="none"),
        ], subtitle=day.isoformat())
    snapshot = state["morning"]["snapshot"]
    final = state["final"]
    returned = int(final[1]) if final else None
    return card("Time Out Report", [
        _stat_row("Morning Expected", str(snapshot["expected"]), margin="md"),
        _stat_row("Morning Attended", str(snapshot["attended"]), margin="xs"),
        _stat_row("No Bus", str(len(state["no_bus"])), margin="xs"),
        _stat_row("Expected School Return", str(state["expected_return"]), margin="xs"),
        _stat_row("Confirmed Returned", str(returned) if returned is not None else "Not Sent", margin="xs"),
    ], [
        _button("Choose Who Won't Take Bus", action("admin_timeout_bus", date=day), margin="none"),
        _button("Send to Group", action("admin_timeout_send", date=day), margin="none"),
    ], subtitle=day.isoformat())


def bus_message(day, page=0, query=None):
    state = time_out.get_state(day)
    if state is None:
        return timeout_message(day)
    query = search_query(query)
    roster = state["morning"]["snapshot"]["students"]
    selected_names = ", ".join(roster[sid]["name"] for sid in state["no_bus"]) or "None selected"
    contents = [paragraph("Search for an attendee to mark or clear No Bus. Transport choices do not change attendance or salary."), _stat_row("No Bus", str(len(state["no_bus"])), margin="md"), paragraph(selected_names), _stat_row("Expected Return", str(state["expected_return"]), margin="xs")]
    buttons = [search_button(day, query=query, bus=True)]
    if query:
        from database.google_sheets import search_active_students
        matched_ids = {str(student["student_id"]) for student in search_active_students(query)}
        candidates = [sid for sid in state["eligible"] if sid in matched_ids or query.casefold() in (sid + " " + roster[sid]["name"]).casefold()]
        page = min(max(0, page), max(0, (len(candidates) - 1) // 5))
        contents.append(paragraph(f"{len(candidates)} matching attendee(s)."))
        for sid in candidates[page * 5:(page + 1) * 5]:
            excluded = sid in state["no_bus"]
            label = ("✓ No Bus · " if excluded else "Bus · ") + roster[sid]["name"]
            buttons.append(_button(label[:40], action("admin_timeout_set_bus", date=day, student=sid, excluded=int(not excluded), page=page, query=query), margin="none"))
        if page:
            buttons.append(_button("Previous Matches", action("admin_timeout_bus", date=day, page=page - 1, query=query), margin="none"))
        if (page + 1) * 5 < len(candidates):
            buttons.append(_button("More Matches", action("admin_timeout_bus", date=day, page=page + 1, query=query), margin="none"))
    buttons.append(_button("Done · Back to Time Out", action("admin_timeout", date=day), margin="none"))
    return card("No-Bus Search", contents, buttons, subtitle=day.isoformat())


def send_message(day, actor, returned=None):
    state = time_out.get_state(day)
    if state is None:
        return timeout_message(day)
    returned = state["expected_return"] if returned is None else returned
    return GroupReportText(time_out.confirm_return(day, returned, actor, state["fingerprint"]))


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
        return bus_message(day, int(get("page", "0")), get("query") or None)
    if name == "admin_timeout_set_bus":
        time_out.set_bus_exception(day, get("student"), get("excluded") == "1")
        return bus_message(day, int(get("page", "0")), get("query") or None)
    if name == "admin_timeout_bus_search":
        begin_search(actor, day, bus=True)
        return card("Search Attendees", [paragraph("Type a student name or ID in the typing area and send. Only morning attendees are included.")], [_button("Cancel Search", action("admin_timeout_bus", date=day), margin="none")], subtitle=day.isoformat())
    if name == "admin_timeout_count":
        return card("Enter Return Count", [paragraph(f"Send /timeout {day.isoformat()} followed by the number who actually returned. For example: /timeout {day.isoformat()} 22")])
    if name in {"admin_timeout_send", "admin_timeout_preview"}:
        raw = get("returned")
        return send_message(day, actor, int(raw) if raw else None)
    if name == "admin_timeout_confirm":
        verify_action(actor, data)
        return GroupReportText(time_out.confirm_return(day, int(get("returned")), actor, get("snapshot")))
    raise ValueError("Unknown Time Out Report action.")
