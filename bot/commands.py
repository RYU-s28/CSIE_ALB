"""Command handlers for the LINE bot."""

from bot.line_client import LineClient


def handle_command(text: str, line_client: LineClient) -> str:
    cleaned = (text or "").strip().lower()
    if cleaned == "hello":
        return "Hello! I am your attendance bot."
    if cleaned == "help":
        return "Commands: hello, help, attendance"
    if cleaned == "attendance":
        return "Attendance tracking is ready."
    return "I did not understand that command."
