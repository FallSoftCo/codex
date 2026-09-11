from aiohttp import ClientConnectionError
from textual.widgets import Label, Select, TextArea

from losangelex_room.client import Room

EVENTS = [
    {
        "id": 1,
        "kind": "message",
        "task": "lobby",
        "author": "you",
        "body": "Maya, check notification privacy.",
        "visibility": "room",
        "data": {},
    },
    {
        "id": 2,
        "kind": "message",
        "task": "lobby",
        "author": "maya",
        "body": "Theo, can the server send a generic alert?",
        "visibility": "room",
        "data": {},
    },
    {
        "id": 3,
        "kind": "message",
        "task": "lobby",
        "author": "theo",
        "body": "Yes. The app fetches task details after you open it.",
        "visibility": "room",
        "data": {},
    },
]


class Preview(Room):
    def __init__(self, draft_path=None):
        super().__init__("http://127.0.0.1:18766", "fixture", draft_path=draft_path)
        self.events = EVENTS

    def watch_room(self):
        self.query_one("#connection", Label).update("Preview · captured room exchange")
        self.run_worker(self.render_events())


async def test_private_drafts_keep_their_recipient_when_switching(tmp_path):
    app = Preview(tmp_path / "draft.json")
    async with app.run_test() as pilot:
        await pilot.pause()
        composer = app.query_one("#composer", TextArea)
        composer.load_text("Room instruction")
        await pilot.pause()
        app.query_one("#recipient", Select).value = "maya"
        await pilot.pause()
        composer.load_text("Private Maya instruction")
        await pilot.pause()
        app.query_one("#recipient", Select).value = "room"
        await pilot.pause()
        assert composer.text == "Room instruction"
        app.query_one("#recipient", Select).value = "maya"
        await pilot.pause()
        assert composer.text == "Private Maya instruction"
    restored = Preview(tmp_path / "draft.json")
    assert restored.drafts == {
        "lobby:room": "Room instruction",
        "lobby:maya": "Private Maya instruction",
    }


def test_room_snapshot(snap_compare):
    assert snap_compare(Preview(), terminal_size=(100, 32))


def test_narrow_room_snapshot(snap_compare):
    assert snap_compare(Preview(), terminal_size=(48, 30))


async def test_unknown_send_retries_original_scope_and_keeps_new_private_draft(tmp_path):
    app = Preview(tmp_path / "draft.json")
    calls = []

    async def request(method, path, payload):
        calls.append((method, path, payload.copy()))
        if len(calls) == 1:
            raise ClientConnectionError("Connection lost after submission")
        return {"id": 4}

    app.request = request
    async with app.run_test() as pilot:
        await pilot.pause()
        composer = app.query_one("#composer", TextArea)
        composer.load_text("Original room instruction")
        await app.action_send().wait()
        app.query_one("#recipient", Select).value = "maya"
        await pilot.pause()
        composer.load_text("Different private draft")
        await app.action_send().wait()
        assert calls[0] == calls[1]
        assert calls[0][2]["visibility"] == "room"
        assert composer.text == "Different private draft"
        assert app.pending is None


class ApprovalPreview(Preview):
    def __init__(self):
        super().__init__()
        self.events = [
            *EVENTS,
            {
                "id": 4,
                "kind": "approval",
                "task": "lobby",
                "author": "rowan",
                "body": "Command: just test -p codex-tui\nDirectory: /work/losangelex/codex-rs\nReason: Run the requested UI checks",
                "visibility": "room",
                "data": {"canAccept": True},
            },
        ]
        self.attention = [{"id": 4}]


def test_live_approval_shows_the_concrete_action(snap_compare):
    assert snap_compare(ApprovalPreview(), terminal_size=(100, 40))
