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


def validate_workflow_note(value):
    """A rejected metadata input can be corrected without repeating file effects."""
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(
            "WORKFLOW_NOTE_REQUIRED",
            "Supply a nonempty outcome note.",
            "Use a concise outcome and canonical evidence references.",
        )
    if len(value) > 4000:
        raise ToolValidationError(
            "WORKFLOW_NOTE_TOO_LONG",
            f"Note is {len(value)} characters; the limit is 4000.",
            "Shorten the note and reference existing evidence IDs. This input was rejected before HTTP. "
            "Correct it only within current authorization; do not repeat file or external effects.",
        )
