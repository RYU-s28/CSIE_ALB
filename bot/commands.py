"""Command handlers for the LINE bot."""

from bot.line_client import LineClient


def handle_command(text: str, line_client: LineClient | None = None) -> str:
    cleaned = (text or "").strip().lower()
    if cleaned in {"hello", "/hello"}:
        return "Hello! I am your attendance bot."
    if cleaned in {"help", "/help"}:
        return "Commands: hello, help, attendance, ping"
    if cleaned in {"attendance", "/attendance"}:
        return "Attendance tracking is ready."
    if cleaned in {"ping", "/ping"}:
        return "Pong!"
    return "I did not understand that command."
