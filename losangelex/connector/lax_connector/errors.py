"""Canonical transport errors shared by CLI, callbacks and imported connectors."""


class HttpFailure(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"Hollywood {status}: {message}")
        self.status = status
