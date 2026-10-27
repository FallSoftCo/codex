"""Backoff for read-only service inspection before resident executor capture."""

import time
from .journal import saved


class AdmissionObservationWait:
    def __init__(self, directory):
        self.path = directory / "admission-observation.json"
        self.failures = 0
        self.retry_at = 0.0
        self.current = None

    def defer(self, error):
        self.failures = min(self.failures + 1, 2**31 - 1)
        delay = min(60, 5 * 2 ** min(self.failures - 1, 4))
        self.retry_at = time.monotonic() + delay
        self.current = {
            "schema": "lax-pre-capture-observation/v1",
            "state": "unavailable",
            "attempt": self.failures,
            "retryNotBefore": time.time() + delay,
            "observation": error.details,
            "boundary": "before-resident-capture-and-inference-reservation",
        }
        saved(self.path, self.current)
        return self.current

    def eligible(self):
        return time.monotonic() >= self.retry_at

    def recovered(self):
        if self.current is not None:
            saved(self.path, {**self.current, "state": "recovered",
                              "recoveredAt": time.time()})
        self.failures, self.retry_at, self.current = 0, 0.0, None
