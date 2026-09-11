"""One room, named teammates, and independently hosted agent sessions."""

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import ClassVar

import aiohttp
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Label, Select, Static, TextArea


class Room(App):
    TITLE = "Losangelex · Hollywood team room"
    CSS = """
    Screen { background: #101820; color: #e0e7ed; }
    #title { height: 2; padding: 0 1; text-style: bold; color: #70dfbb; }
    #scope { height: auto; min-height: 3; }
    #task { width: 1fr; }
    #recipient { width: 1fr; }
    #connection { height: auto; padding: 0 1; color: #d6b56c; }
    #timeline { height: 1fr; padding: 0 1; }
    .message { margin-bottom: 1; height: auto; }
    .message Button { height: 1; min-height: 1; width: auto; min-width: 8; border: none; padding: 0; }
    #composer { height: 5; border: round #547080; }
    #actions { height: 3; }
    Button { min-width: 10; width: 1fr; }
    #question { height: auto; color: #efc26d; padding: 0 1; }
    """
    BINDINGS: ClassVar = [
        ("ctrl+enter", "send", "Send"),
        ("ctrl+q", "quit", "Disconnect"),
        ("ctrl+l", "room", "Room"),
        ("ctrl+o", "status", "Status"),
    ]

    def __init__(self, url, token, *, draft_path=None):
        super().__init__()
        self.url, self.token = url.rstrip("/"), token
        self.draft_path = draft_path
        self.cursor, self.events = 0, []
        self.task_id, self.recipient = "lobby", "room"
        self.drafts, self.pending = {}, None
        self.pending_control = None
        self.reply_to = None
        self.session = None
        self.attention = []
        self.render_lock = asyncio.Lock()
        self.task_options = [("Project room", "lobby")]
        if draft_path and draft_path.exists():
            saved = json.loads(draft_path.read_text())
            if saved.get("url") == self.url:
                self.drafts = saved.get("drafts", {})
                self.pending = saved.get("pending")
                self.pending_control = saved.get("pendingControl")

    def compose(self) -> ComposeResult:
        yield Label("LOSANGELEX  ·  Hollywood team room", id="title")
        with Horizontal(id="scope"):
            yield Select([("Project room", "lobby")], value="lobby", allow_blank=False, id="task")
            yield Select(
                [
                    ("Shared room", "room"),
                    *[
                        (f"Direct · {a.title()}", a)
                        for a in ("coordinator", "maya", "theo", "rowan")
                    ],
                ],
                value="room",
                allow_blank=False,
                id="recipient",
            )
        yield Label("Connecting…", id="connection")
        yield VerticalScroll(id="timeline")
        yield Label("", id="question")
        yield TextArea(id="composer", soft_wrap=True)
        with Horizontal(id="actions"):
            yield Button("Send", id="send", variant="primary")
            yield Button("Needs you", id="needs")
            yield Button("Status", id="status")
            yield Button("Stop", id="stop")
        yield Footer()

    async def on_mount(self):
        self.session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {self.token}"})
        self.query_one("#composer", TextArea).load_text(self.drafts.get(self.scope_key(), ""))
        self.query_one("#composer").focus()
        self.watch_room()

    def scope_key(self):
        return f"{self.task_id}:{self.recipient}"

    def save(self):
        self.drafts[self.scope_key()] = self.query_one("#composer", TextArea).text
        if self.draft_path:
            self.draft_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.draft_path.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(
                    {
                        "url": self.url,
                        "drafts": self.drafts,
                        "pending": self.pending,
                        "pendingControl": self.pending_control,
                    },
                    stream,
                )
            temporary.replace(self.draft_path)

    async def on_unmount(self):
        if self.session:
            await self.session.close()

    def on_text_area_changed(self, event):
        self.save()

    async def on_select_changed(self, event):
        if event.value is Select.BLANK:
            return
        self.save()
        if event.select.id == "task":
            self.task_id = event.value
        else:
            self.recipient = event.value
        self.reply_to = None
        self.query_one("#question", Label).update("")
        self.query_one("#composer", TextArea).load_text(self.drafts.get(self.scope_key(), ""))
        await self.render_events()

    async def render_events(self):
        async with self.render_lock:
            await self.render_timeline()

    async def render_timeline(self):
        timeline = self.query_one("#timeline", VerticalScroll)
        at_end = timeline.is_vertical_scroll_end
        await timeline.remove_children()
        visibility = "room" if self.recipient == "room" else f"direct:{self.recipient}"
        cards = []
        open_items = {item["id"] for item in self.attention}
        for event in self.events[-500:]:
            if event["visibility"] != visibility or (
                self.task_id != "lobby" and event["task"] != self.task_id
            ):
                continue
            if event["kind"] not in (
                "message",
                "attention",
                "approval",
                "task",
                "control",
                "resolved",
            ):
                continue
            text = Text()
            text.append(
                event["author"].title(),
                style="bold #70dfbb" if event["author"] != "you" else "bold",
            )
            text.append(f"  · {event['task']}  · #{event['id']}\n", style="dim")
            text.append(event["body"])
            if event["kind"] == "approval":
                cards.append(
                    Vertical(
                        Static(text),
                        Button(
                            "Approve once",
                            id=f"accept-{event['id']}",
                            disabled=event["id"] not in open_items
                            or not event["data"].get("canAccept"),
                        ),
                        Button(
                            "Decline",
                            id=f"decline-{event['id']}",
                            disabled=event["id"] not in open_items,
                        ),
                        classes="message",
                    )
                )
            else:
                cards.append(
                    Vertical(
                        Static(text),
                        Button(
                            "Answer" if event["kind"] == "attention" else "Reply",
                            id=f"reply-{event['id']}",
                            disabled=event["kind"] == "attention" and event["id"] not in open_items,
                        ),
                        classes="message",
                    )
                )
        if cards:
            await timeline.mount(*cards)
        if at_end:
            timeline.scroll_end(animate=False)

    async def request(self, method, path, payload=None):
        async with self.session.request(
            method,
            self.url + "/hollywood/v2/" + path,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            body = await response.json()
            if response.status >= 400:
                raise ValueError(body.get("error", f"HTTP {response.status}"))
            return body

    @work(exclusive=True, group="connection")
    async def watch_room(self):
        delay = 1
        while True:
            try:
                snapshot = await self.request("GET", "overview")
                self.attention = snapshot["attention"]
                self.task_options = [(t["title"], t["id"]) for t in snapshot["tasks"]]
                with self.prevent(Select.Changed):
                    self.query_one("#task", Select).set_options(self.task_options)
                    self.query_one("#task", Select).value = self.task_id
                if self.pending:
                    try:
                        receipt = await self.request(
                            "GET", f"commands/{self.pending['payload']['commandId']}"
                        )
                        composer = self.query_one("#composer", TextArea)
                        if (
                            self.scope_key() == self.pending["scope"]
                            and composer.text.strip() == self.pending["payload"]["body"]
                        ):
                            composer.clear()
                        self.pending = None
                        self.save()
                        self.notify(f"Submission reconciled · #{receipt['event']['id']}")
                    except (ValueError, aiohttp.ContentTypeError):
                        self.notify(
                            "Unconfirmed submission retained. Send retries the same command ID."
                        )
                status = (
                    "Connected · address a name to talk in the room"
                    if snapshot.get("runtimeReady")
                    else "Connected · Codex runtime needs attention"
                )
                self.query_one("#connection", Label).update(status)
                async with self.session.get(
                    self.url + f"/hollywood/v2/events?after={self.cursor}",
                    timeout=aiohttp.ClientTimeout(total=None, sock_read=30),
                ) as response:
                    response.raise_for_status()
                    async for line in response.content:
                        if line.startswith(b"data: "):
                            event = json.loads(line[6:])
                            if event["id"] > self.cursor:
                                self.cursor = event["id"]
                                self.events.append(event)
                                self.events = self.events[-1000:]
                                if event["kind"] in ("attention", "approval"):
                                    self.attention.append({"id": event["id"]})
                                if event["kind"] == "resolved":
                                    self.attention = [
                                        a
                                        for a in self.attention
                                        if a["id"] != event["data"].get("attention")
                                    ]
                                if event["kind"] == "task" and event["task"] not in {
                                    value for _, value in self.task_options
                                }:
                                    self.task_options.append((event["body"], event["task"]))
                                    with self.prevent(Select.Changed):
                                        self.query_one("#task", Select).set_options(
                                            self.task_options
                                        )
                                        self.query_one("#task", Select).value = self.task_id
                                await self.render_events()
                    delay = 1
            except (aiohttp.ClientError, OSError, ValueError, asyncio.TimeoutError) as exc:
                self.query_one("#connection", Label).update(
                    f"Disconnected · draft retained · retrying in {delay}s · {type(exc).__name__}"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    @work(group="send", exclusive=True)
    async def action_send(self):
        composer = self.query_one("#composer", TextArea)
        text = composer.text.strip()
        if not text and not self.pending:
            return
        if self.pending is None:
            payload = {
                "commandId": str(uuid.uuid4()),
                "body": text,
                "task": self.task_id,
                "visibility": "room" if self.recipient == "room" else "direct",
                "targets": [] if self.recipient == "room" else [self.recipient],
            }
            path = "messages"
            if self.reply_to:
                payload["replyTo"] = self.reply_to
                source = next(e for e in self.events if e["id"] == self.reply_to)
                if source["kind"] == "attention":
                    path = f"attention/{self.reply_to}/answer"
                    payload = {"commandId": payload["commandId"], "body": text}
            self.pending = {"payload": payload, "path": path, "scope": self.scope_key()}
        self.save()
        try:
            submitted = self.pending
            await self.request("POST", submitted["path"], submitted["payload"])
            self.pending = None
            if (
                self.scope_key() == submitted["scope"]
                and composer.text.strip() == submitted["payload"]["body"]
            ):
                composer.clear()
            self.reply_to = None
            self.save()
        except (aiohttp.ClientError, ValueError, asyncio.TimeoutError) as exc:
            self.notify(
                f"Submission unconfirmed: {exc}. Send retries its original scope.",
                severity="warning",
            )

    async def on_button_pressed(self, event):
        if event.button.id.startswith(("accept-", "decline-")):
            decision, event_id = event.button.id.split("-", 1)
            try:
                await self.request("POST", f"approval/{event_id}/answer", {"decision": decision})
                event.button.disabled = True
                self.notify("Approval response submitted")
            except (aiohttp.ClientError, ValueError, asyncio.TimeoutError) as exc:
                self.notify(str(exc), severity="warning")
        elif event.button.id.startswith("reply-"):
            reply_to = int(event.button.id.removeprefix("reply-"))
            source = next(e for e in self.events if e["id"] == reply_to)
            self.save()
            self.task_id = source["task"]
            self.recipient = (
                "room" if source["visibility"] == "room" else source["visibility"].split(":", 1)[1]
            )
            with self.prevent(Select.Changed):
                self.query_one("#task", Select).value = self.task_id
                self.query_one("#recipient", Select).value = self.recipient
            self.query_one("#composer", TextArea).load_text(self.drafts.get(self.scope_key(), ""))
            self.reply_to = reply_to
            self.query_one("#question", Label).update(
                f"Replying to #{self.reply_to} · {source['author']} · {source['task']}"
            )
            self.query_one("#composer").focus()
        elif event.button.id == "send":
            self.action_send()
        elif event.button.id == "status":
            await self.action_status()
        elif event.button.id == "needs":
            try:
                snapshot = await self.request("GET", "overview")
                text = "\n".join(
                    f"#{a['id']} · {a['agent']} · {a['task']}" for a in snapshot["attention"]
                )
                self.query_one("#question", Label).update(text or "Nothing needs your attention")
            except (aiohttp.ClientError, ValueError, asyncio.TimeoutError):
                self.notify(
                    "Host unavailable; reconnect to refresh pending questions", severity="warning"
                )
        elif event.button.id == "stop":
            if self.recipient == "room" and self.pending_control is None:
                self.notify("Select a teammate in the recipient control to stop its current task.")
                return
            if self.pending_control is None:
                self.pending_control = {
                    "commandId": str(uuid.uuid4()),
                    "task": self.task_id,
                    "agent": self.recipient,
                    "action": "interrupt",
                }
            self.save()
            try:
                result = await self.request("POST", "control", self.pending_control)
                self.pending_control = None
                self.save()
                self.notify(f"{result['agent']}: {result['state']}")
            except (aiohttp.ClientError, ValueError, asyncio.TimeoutError):
                self.notify(
                    "Interruption unconfirmed; Stop retries its original target", severity="warning"
                )

    async def action_status(self):
        try:
            snapshot = await self.request("GET", "overview")
            text = " · ".join(
                f"{a['agent']} / {a['task']}: {a['status']}" for a in snapshot["agents"]
            )
            self.query_one("#question", Label).update(text or "No agents working yet")
        except (aiohttp.ClientError, ValueError):
            self.notify("Host unavailable; last room state retained", severity="warning")

    def action_room(self):
        self.query_one("#recipient", Select).value = "room"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18766")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument(
        "--drafts", type=Path, default=Path.home() / ".local/state/losangelex-room/drafts.json"
    )
    args = parser.parse_args()
    Room(args.url, args.token_file.read_text().strip(), draft_path=args.drafts).run()
