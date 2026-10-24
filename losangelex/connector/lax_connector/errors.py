"""Canonical transport errors shared by CLI, callbacks and imported connectors."""
import re


class HttpFailure(RuntimeError):
    def __init__(self, status, message, *, code=None, next_action=None):
        super().__init__(f"Hollywood {status}: {message}")
        self.status = status
        self.code = code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) else None
        self.next_action = (next_action if isinstance(next_action, str)
                            and 0 < len(next_action) <= 1500 else None)

    def public_details(self):
        return {"status": self.status, "message": str(self)[:250],
                **({"code": self.code} if self.code else {}),
                "next": self.next_action or
                    "Inspect the current authorized resource/revision before a corrected command"}


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
