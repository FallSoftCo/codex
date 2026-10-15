"""Canonical transport errors shared by CLI, callbacks and imported connectors."""


class HttpFailure(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"Hollywood {status}: {message}")
        self.status = status


class ToolValidationError(ValueError):
    """Known caller-correctable validation with deliberately public guidance."""

    def __init__(self, code, message, next_action):
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action

    def public_details(self):
        return {
            "code": self.code,
            "message": self.message,
            "next": self.next_action,
        }
