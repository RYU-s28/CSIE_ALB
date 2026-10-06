"""Command handlers for the LINE bot."""

from bot.line_client import LineClient


COMMAND_RESPONSES = {
    "hello": "Hello! I am your attendance bot.",
    "help": (
        "Commands: hello, help, attendance, ping, statusme, summary, "
        "report, absent, status"
    ),
    "attendance": "Attendance tracking is ready.",
}


def normalize_command(text: str) -> str:
    cleaned = (text or "").strip().lower()
    return cleaned.removeprefix("/")


def get_command_response(text: str) -> str | None:
    return COMMAND_RESPONSES.get(normalize_command(text))


def handle_command(text: str, line_client: LineClient | None = None) -> str:
    command = normalize_command(text)
    response = get_command_response(command)
    if response is not None:
        return response
    if command == "ping":
        return "Pong!"
    return "I did not understand that command."
