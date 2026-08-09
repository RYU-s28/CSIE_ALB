"""Database helpers and connection placeholders."""

from typing import Optional


class Database:
    def __init__(self) -> None:
        self.connection: Optional[object] = None

    def connect(self) -> None:
        self.connection = object()

    def disconnect(self) -> None:
        self.connection = None
