"""Deliver official reports and retain actionable, request-local failures."""
from contextvars import ContextVar
import json
import re

from linebot.v3.messaging import ApiClient, MessagingApi, PushMessageRequest, TextMessage

report_failure = ContextVar("report_failure", default="")


def report_chunks(text, limit=4900):
    """LINE measures text in UTF-16 code units, including surrogate pairs."""
    chunk, size = [], 0
    for character in text:
        width = 2 if ord(character) > 0xFFFF else 1
        if size + width > limit:
            yield "".join(chunk)
            chunk, size = [], 0
        chunk.append(character)
        size += width
    if chunk:
        yield "".join(chunk)


def delivery_error(error):
    status = getattr(error, "status", None)
    try:
        body = json.loads(getattr(error, "body", "") or "{}")
    except (ValueError, TypeError):
        body = {}
    message = str(body.get("message", "")) if isinstance(body, dict) else ""
    if status == 429:
        if "month" in message.lower() or "quota" in message.lower():
            return "LINE's monthly message quota is exhausted. Increase the messaging plan or wait for the quota to reset."
        return "LINE rejected the report because of a message limit. Check the monthly quota and retry later if rate limited."
    if status == 401:
        return "LINE rejected the channel access token. Update LINE_CHANNEL_ACCESS_TOKEN for this bot's Messaging API channel."
    if status == 403:
        return "LINE denied access. Check the channel permissions and that this bot can access the report group."
    if status == 400:
        return "LINE rejected the destination or report message. Verify LINE_REPORT_GROUP_ID came from this bot's group webhook and that the bot is still a member. Check the server log for LINE's error details."
    return "Report delivery could not be confirmed. Check the server log before retrying to avoid duplicate reports."


def send_report(configuration, group_id, report):
    report_failure.set("")
    if not isinstance(report, str) or not report.strip() or report.strip().lower() in {"none", "null"}:
        report_failure.set("The report is empty or invalid. Generate the report again.")
        print("GROUP REPORT SKIPPED: invalid or empty report.")
        return False
    if not re.fullmatch(r"C[0-9a-fA-F]{32}", group_id):
        report_failure.set("Set LINE_REPORT_GROUP_ID to the C followed by 32 hexadecimal characters from this bot's group webhook.")
        print("GROUP REPORT SKIPPED: missing or malformed LINE_REPORT_GROUP_ID.")
        return False
    sent_batches = 0
    try:
        with ApiClient(configuration) as client:
            api = MessagingApi(client)
            chunks = list(report_chunks(report))
            for start in range(0, len(chunks), 5):
                api.push_message(push_message_request=PushMessageRequest(
                    to=group_id, messages=[TextMessage(text=chunk) for chunk in chunks[start:start + 5]],
                ), _request_timeout=(3.0, 15.0))
                sent_batches += 1
        return True
    except Exception as error:
        reason = delivery_error(error)
        if sent_batches:
            reason = "Part of the report was sent. " + reason + " Retrying the full report can duplicate earlier parts."
        report_failure.set(reason)
        # Do not log exception headers: they may contain credentials. LINE's
        # structured body explains rejected fields and quota failures.
        body = getattr(error, "body", None)
        headers = getattr(error, "headers", None) or {}
        print("GROUP REPORT SEND ERROR:", json.dumps({
            "type": type(error).__name__, "status": getattr(error, "status", None),
            "request_id": headers.get("x-line-request-id"),
            "body": body, "sent_batches": sent_batches,
        }, ensure_ascii=True, default=str))
        return False
