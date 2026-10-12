"""Compatibility wrapper for the private, card-based LINE response path."""


class LineClient:
    def reply(self, reply_token: str, text: str) -> bool:
        from app import reply_to_line
        return bool(reply_to_line(reply_token, text))
