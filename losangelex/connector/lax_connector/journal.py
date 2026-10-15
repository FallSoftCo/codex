"""Crash-consistent private operation receipts and execution-attempt journals."""

import json
import os
import tempfile
from pathlib import Path
from uuid import UUID


def _sync(path):
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_saved(path, value):
    path = Path(path)
    descriptor, filename = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        _sync(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def saved(path, value):
    if isinstance(path, ExecutionJournal):
        path.save_json(value)
    else:
        _atomic_saved(path, value)


def execution_key(value):
    delivery = value["delivery"]
    generation = delivery["generation"]
    claim = delivery["claim_id"]
    if type(generation) is not int or generation < 1:
        raise ValueError("Invalid execution generation")
    if not isinstance(claim, str) or not claim or len(claim) > 512:
        raise ValueError("Invalid execution claim")
    return {
        "deliveryId": str(UUID(delivery["id"])),
        "generation": generation,
        "claimId": claim,
    }


def execution_scope(value):
    delivery, request = value["delivery"], value["request"]
    if (
        delivery["event"] != request["id"]
        or delivery["authority"] != request["authority"]
    ):
        raise ValueError("Execution source event changed")
    return {
        "key": execution_key(value),
        "agentId": delivery["agent"],
        "hostId": delivery["host"],
        "authorityId": delivery["authority"],
        "request": request,
    }


class ExecutionJournal:
    """A handle pinned to one delivery, generation and original claim."""

    def __init__(self, store, key):
        self.store, self.key = store, key

    @property
    def path(self):
        if self.key is None:
            raise FileNotFoundError("No captured execution attempt")
        return self.store.path(self.key)

    @property
    def directory(self):
        return self.path.parent

    def __fspath__(self):
        return os.fspath(self.path)

    def exists(self):
        return self.key is not None and self.path.exists()

    def read_text(self):
        text = self.path.read_text()
        value = json.loads(text)
        self.store.validate(value)
        if execution_key(value) != self.key:
            raise RuntimeError("Captured execution owner changed")
        return text

    def save_json(self, value):
        self.store.validate(value)
        if execution_key(value) != self.key:
            raise RuntimeError("Attempt writer cannot change execution ownership")
        before = json.loads(self.read_text()) if self.exists() else None
        if before is not None and execution_scope(before) != execution_scope(value):
            raise RuntimeError("Captured execution scope is immutable")
        if self.store.is_unsettled(value):
            self.store.mark_open(self.key)
        _atomic_saved(self.path, value)
        # An older attempt is never allowed to select itself or overwrite a
        # later context projection merely because its receipt was reconciled.
        if self.store.selected_key() == self.key:
            _atomic_saved(self.store.projection, value)
        if not self.store.is_unsettled(value):
            self.store.close_index(self.key)


class ExecutionJournals:
    def __init__(self, state, *, agent, host):
        self.state, self.agent, self.host = Path(state), agent, host
        self.root = self.state / "executions"
        self.root.mkdir(mode=0o700, exist_ok=True)
        _sync(self.state)
        self.open_index = self.root / "open"
        self.open_index.mkdir(mode=0o700, exist_ok=True)
        _sync(self.root)
        self.selection = self.state / "execution-current.json"
        self.projection = self.state / "execution.json"
        if self.selection.exists():
            current = self.current()
            value = json.loads(current.read_text())
            # Canonical attempt precedes selection; selection precedes the
            # compatibility projection. Recover either interrupted boundary.
            if (
                not self.projection.exists()
                or json.loads(self.projection.read_text()) != value
            ):
                _atomic_saved(self.projection, value)
        elif self.projection.exists():
            value = json.loads(self.projection.read_text())
            self.validate(value)
            key = execution_key(value)
            self._directory(key)
            journal = ExecutionJournal(self, key)
            if journal.exists():
                canonical = json.loads(journal.read_text())
                if execution_scope(canonical) != execution_scope(value):
                    raise RuntimeError(
                        "Existing attempt conflicts with imported execution"
                    )
                value = canonical
            else:
                if self.is_unsettled(value):
                    self.mark_open(key)
                _atomic_saved(journal.path, value)
            if self.is_unsettled(value):
                self.mark_open(key)
            self._select(journal, value)

    @staticmethod
    def is_unsettled(value):
        return value["state"] not in ("completed", "failed", "cancelled") or value.get(
            "goalLifecyclePending", False
        )

    def index_path(self, key):
        return self.open_index / (key["deliveryId"] + "." + str(key["generation"]))

    def mark_open(self, key):
        path = self.index_path(key)
        target = os.path.relpath(self.path(key), self.open_index)
        try:
            os.symlink(target, path)
            _sync(self.open_index)
        except FileExistsError:
            if not path.is_symlink() or os.readlink(path) != target:
                raise RuntimeError(
                    "Open execution index conflicts with its canonical attempt"
                )

    def close_index(self, key):
        path = self.index_path(key)
        if path.is_symlink():
            expected = os.path.relpath(self.path(key), self.open_index)
            if os.readlink(path) != expected:
                raise RuntimeError("Open execution index changed target")
            path.unlink()
            _sync(self.open_index)
        elif path.exists():
            raise RuntimeError("Open execution index is not a canonical reference")

    def validate(self, value):
        scope = execution_scope(value)
        if scope["agentId"] != self.agent or scope["hostId"] != self.host:
            raise RuntimeError("Execution journal belongs to another enrolled owner")

    def path(self, key):
        return (
            self.root
            / str(UUID(key["deliveryId"]))
            / str(key["generation"])
            / "execution.json"
        )

    def _directory(self, key):
        parent = self.root / key["deliveryId"]
        parent.mkdir(mode=0o700, exist_ok=True)
        _sync(self.root)
        self.path(key).parent.mkdir(mode=0o700, exist_ok=True)
        _sync(parent)

    def selected_key(self):
        if not self.selection.exists():
            return None
        key = json.loads(self.selection.read_text())
        if set(key) != {"deliveryId", "generation", "claimId"}:
            raise RuntimeError("Invalid current execution selector")
        if (
            str(UUID(key["deliveryId"])) != key["deliveryId"]
            or type(key["generation"]) is not int
            or key["generation"] < 1
        ):
            raise RuntimeError("Invalid current execution identity")
        return key

    def current(self):
        return ExecutionJournal(self, self.selected_key())

    def _select(self, journal, value):
        _atomic_saved(self.selection, journal.key)
        _atomic_saved(self.projection, value)

    def begin(self, value):
        self.validate(value)
        key = execution_key(value)
        self._directory(key)
        journal = ExecutionJournal(self, key)
        if journal.exists():
            raise RuntimeError(
                "Original attempt already captured; reconcile without replay"
            )
        journal.save_json(value)
        self._select(journal, value)
        return journal

    def open(self, delivery, generation):
        if type(generation) is not int or generation < 1:
            raise ValueError("Positive original generation required")
        path = self.path({"deliveryId": str(UUID(delivery)), "generation": generation})
        value = json.loads(path.read_text())
        self.validate(value)
        return ExecutionJournal(self, execution_key(value))

    def records(self):
        result = []
        for path in sorted(self.root.glob("*/*/execution.json")):
            value = json.loads(path.read_text())
            self.validate(value)
            if path != self.path(execution_key(value)):
                raise RuntimeError("Execution attempt stored under another identity")
            result.append(value)
        return result

    def unsettled(self):
        result = []
        for path in sorted(self.open_index.iterdir()):
            # A dangling write-ahead reference is an uncertain capture, not
            # evidence that another native attempt may be started.
            value = json.loads(path.read_text())
            self.validate(value)
            key = execution_key(value)
            if (
                path != self.index_path(key)
                or not path.is_symlink()
                or os.readlink(path) != os.path.relpath(self.path(key), self.open_index)
            ):
                raise RuntimeError("Open execution reference has another owner")
            if self.is_unsettled(value):
                result.append(value)
            else:
                self.close_index(key)
        return result
