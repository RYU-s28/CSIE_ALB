"""Webhook entry points for the bot."""

from flask import Flask, jsonify, request

from attendance.attendance import AttendanceTracker
from bot.commands import handle_command


def create_app() -> Flask:
    app = Flask(__name__)
    tracker = AttendanceTracker()

    @app.get("/")
    def health() -> tuple[dict, int]:
        return jsonify({"status": "ok"}), 200

    @app.post("/webhook")
    def webhook() -> tuple[dict, int]:
        payload = request.get_json(silent=True) or {}
        if payload.get("type") == "message":
            text = payload.get("message", {}).get("text", "")
            reply_text = handle_command(text, tracker, payload.get("user_id"))
            return jsonify({"status": "ok", "reply": reply_text}), 200
        return jsonify({"status": "ok"}), 200

    return app
