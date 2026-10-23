"""Synthetic mailbox store for authentication acceptance. Never emulates Exchange.

Intentionally ephemeral: one replica in the local stand, reset on restart.
"""

import base64
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4


class DemoBackend:
    name = "demo"

    def __init__(self):
        self._mail = {}
        self._events = {}
        self._lock = RLock()

    def _box(self, mailbox):
        if mailbox not in self._mail:
            self._mail[mailbox] = {
                "welcome-" + mailbox: {
                    "id": "welcome-" + mailbox,
                    "folder": "inbox",
                    "subject": "[SYNTHETIC] Стенд Outlook MCP",
                    "body": "Тестовое письмо для " + mailbox + ". Это не данные Exchange.",
                    "sender": "stand@lab.example",
                    "to": [mailbox],
                    "is_read": False,
                    "received": "2026-10-23T09:00:00+00:00",
                    "attachments": [{"name": "stand-note.txt", "size": len(self._attachment(mailbox))}],
                    "synthetic": True,
                }
            }
        return self._mail[mailbox]

    def list_folders(self, mailbox):
        return [{"name": n} for n in ["inbox", "sent", "drafts", "trash"]]

    def list_mail(self, mailbox, folder, limit, query):
        with self._lock:
            return deepcopy(
                [
                    v
                    for v in self._box(mailbox).values()
                    if v["folder"] == folder
                    and query.casefold() in (v["subject"] + " " + v["body"]).casefold()
                ][:limit]
            )

    def get_mail(self, mailbox, item_id, folder):
        with self._lock:
            msg = self._box(mailbox).get(item_id)
            if not msg or msg["folder"] != folder:
                raise LookupError("Item not found in this mailbox/folder")
            return deepcopy(msg)

    def get_attachment(self, mailbox, item_id, folder, name):
        message = self.get_mail(mailbox, item_id, folder)
        if not any(attachment["name"] == name for attachment in message["attachments"]):
            raise LookupError("File attachment not found")
        return {
            "name": name,
            "content_base64": base64.b64encode(self._attachment(mailbox)).decode(),
            "synthetic": True,
        }

    @staticmethod
    def _attachment(mailbox):
        return ("Synthetic attachment for " + mailbox + "\n").encode()

    def save_draft(self, mailbox, to, subject, body, cc, bcc):
        with self._lock:
            item_id = str(uuid4())
            msg = {
                "id": item_id,
                "folder": "drafts",
                "subject": subject,
                "body": body,
                "sender": mailbox,
                "to": to,
                "cc": cc,
                "bcc": bcc,
                "is_read": True,
                "received": datetime.now(timezone.utc).isoformat(),
                "attachments": [],
                "synthetic": True,
            }
            self._box(mailbox)[item_id] = msg
            return deepcopy(msg)

    def send_draft(self, mailbox, item_id):
        with self._lock:
            self.get_mail(mailbox, item_id, "drafts")
            self._box(mailbox)[item_id]["folder"] = "sent"
            return {"status": "sent", "synthetic": True, "id": item_id}

    def update_mail(self, mailbox, item_id, folder, is_read):
        with self._lock:
            self.get_mail(mailbox, item_id, folder)
            self._box(mailbox)[item_id]["is_read"] = is_read
            return {"status": "updated", "synthetic": True}

    def move_mail(self, mailbox, item_id, folder, destination):
        with self._lock:
            self.get_mail(mailbox, item_id, folder)
            if destination not in {"inbox", "drafts", "sent", "trash"}:
                raise ValueError("Unknown destination")
            if destination == "drafts":
                raise ValueError("Existing mail cannot be converted to a draft")
            self._box(mailbox)[item_id]["folder"] = destination
            return {"status": "moved", "synthetic": True, "destination": destination}

    def search_contacts(self, mailbox, query, limit):
        contact = {"name": "Synthetic contact", "email": "stand@lab.example", "synthetic": True}
        return (
            [contact][:limit]
            if query.casefold() in (contact["name"] + " " + contact["email"]).casefold()
            else []
        )

    def list_events(self, mailbox, start, end, limit):
        with self._lock:
            return deepcopy(
                [
                    v
                    for v in self._events.get(mailbox, {}).values()
                    if datetime.fromisoformat(v["start"]) < datetime.fromisoformat(end)
                    and datetime.fromisoformat(v["end"]) > datetime.fromisoformat(start)
                ][:limit]
            )

    def save_event(self, mailbox, subject, start, end, location):
        with self._lock:
            item = {
                "id": str(uuid4()),
                "subject": subject,
                "start": start,
                "end": end,
                "location": location,
                "synthetic": True,
            }
            self._events.setdefault(mailbox, {})[item["id"]] = item
            return deepcopy(item)
