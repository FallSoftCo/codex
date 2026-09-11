"""Loopback-only chat fixtures for transport and UI tests; no live agents or push sender."""

import argparse
import tempfile
from pathlib import Path

from aiohttp import web
from hollywood_room.server import Service, application
from hollywood_room.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18768)
    args = parser.parse_args()
    temporary = tempfile.TemporaryDirectory(prefix="losangelex-chat-fixture-")
    store = Store(Path(temporary.name) / "room.db")
    if not store.rows("SELECT id FROM event LIMIT 1"):
        scripts = [
            ("you", "Let’s make the Android room feel like a real chat app."),
            (
                "coordinator",
                "I’ll keep the work connected. Maya owns the interface, Theo owns history, and Rowan will check the result.",
            ),
            (
                "maya",
                "The composer is ready. Each teammate has a distinct identity, and replies keep the original message in view.",
            ),
            (
                "theo",
                "History loads in pages as you scroll. New messages arrive without losing your place.",
            ),
            (
                "rowan",
                "I checked long conversations, reconnects, and private replies. The original task and recipient stay attached.",
            ),
        ]
        with store.db:
            for index in range(650):
                author, body = scripts[index % len(scripts)]
                store.event(
                    "message",
                    "lobby",
                    author,
                    f"{body}\n\nHistory reference {index:04d}.",
                )
            for agent in ("coordinator", "maya", "theo", "rowan"):
                store.event(
                    "message",
                    "lobby",
                    agent,
                    "This is our private conversation. Messages here stay separate from the team room.",
                    visibility=f"direct:{agent}",
                )
            store.add_task("chat-design", "Android chat experience", None)
            store.event(
                "message",
                "chat-design",
                "maya",
                "The new chat layout is ready to review.\n\n• Clear names and distinct avatars\n• Quoted replies\n• Older messages as you scroll",
            )
            store.event(
                "message",
                "chat-design",
                "you",
                "Keep the composer comfortable and make it easy to jump into any teammate’s conversation.",
            )
            store.event(
                "message",
                "chat-design",
                "theo",
                "The history API is ready. I’ve checked that new messages cannot create gaps in an older page.",
            )
            store.event(
                "message",
                "chat-design",
                "rowan",
                "I’ll test scrolling past 500 messages, then send a reply from the original task.",
            )
    app = application(Service(store, "android-fixture"))
    try:
        web.run_app(app, host="127.0.0.1", port=args.port, access_log=None)
    finally:
        store.close()
        temporary.cleanup()


if __name__ == "__main__":
    main()
