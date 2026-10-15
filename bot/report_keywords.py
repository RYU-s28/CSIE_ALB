"""Explicit admin group report requests, using the event's free Reply API."""
import os

REPORT_KEYWORDS = {"上班點名", "下班點名"}


def handle_report_keyword(event, day):
    text = (getattr(event.message, "text", "") or "").strip()
    if text not in REPORT_KEYWORDS:
        return False
    from app import send_report_reply
    from bot.commands import is_admin_user
    source = event.source
    if not is_admin_user(getattr(source, "user_id", None)):
        return True
    group_id = getattr(source, "group_id", None)
    configured = os.getenv("LINE_REPORT_GROUP_ID", "").strip()
    if getattr(source, "type", "") != "group" or not group_id:
        send_report_reply(event.reply_token, "Send 上班點名 or 下班點名 in the report group to publish a report.")
        return True
    if configured and group_id != configured:
        send_report_reply(event.reply_token, "Please send this keyword in the configured report group.")
        return True
    try:
        from scheduler.work_calendar import is_workday
        if not is_workday(day):
            raise ValueError("This is a rest day. No attendance report is scheduled.")
        if text == "上班點名":
            from scheduler.daily_report import generate_daily_report
            report = generate_daily_report(day)
        else:
            from attendance.time_out import get_state, confirm_return
            state = get_state(day)
            if state is None:
                raise ValueError("Send 上班點名 first to save today's morning report before issuing 下班點名.")
            report = confirm_return(day, state["expected_return"], source.user_id, state["fingerprint"])
        send_report_reply(event.reply_token, report)
    except (ValueError, RuntimeError) as error:
        send_report_reply(event.reply_token, str(error))
    except Exception as error:
        print("KEYWORD REPORT ERROR:", type(error).__name__)
        send_report_reply(event.reply_token, "The report could not be prepared. Please check the server logs and try again.")
    return True
