"""Exercise every advertised tool through existing LiteLLM using real Keycloak OAuth2.

Safe for synthetic backend only. No real Exchange messages or external LLM calls.
"""

import base64
import hashlib
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from acceptance import ROOT, content, gateway_call, oauth_login
from litellm_admin import BASE, checked

TOOLS = {
    "whoami",
    "list_folders",
    "search_emails",
    "get_email",
    "get_attachment",
    "save_draft",
    "send_draft",
    "mark_email_read",
    "move_email",
    "search_contacts",
    "list_events",
    "save_event",
}
INTERVAL = {"start": "2026-11-02T09:00:00+03:00", "end": "2026-11-02T11:00:00+03:00"}


class Runner:
    def __init__(self):
        self.calls = []
        self.tools = {name: {"positive": 0, "negative": 0, "scenarios": []} for name in sorted(TOOLS)}

    def call(self, client, tool, args=None, *, denied=False, check=None, case=""):
        result = gateway_call(client, tool, args)
        is_error = bool(result.get("isError") or result.get("result", {}).get("isError"))
        assert is_error == denied, f"{tool}: unexpected error status in {case}"
        value = None if denied else content(result)
        if check is not None:
            assert check(value), f"{tool}: semantic assertion failed in {case}"
        self.tools[tool]["negative" if denied else "positive"] += 1
        self.tools[tool]["scenarios"].append(case)
        self.calls.append(
            {"tool": tool, "case": case, "expected": "denied" if denied else "success", "status": "PASS"}
        )
        return value


def main():
    # Do not let this test accidentally create/send real mail after switching to EWS.
    with httpx.Client(timeout=10) as direct:
        health = checked(direct.get("http://localhost:8766/healthz"))
        assert health["backend"] == "demo", "This acceptance script must never run on a real EWS backend"
    keys = json.loads((ROOT / ".local/litellm-user-keys.json").read_text())
    runner = Runner()
    clients = {}
    run_id = uuid.uuid4().hex[:12]
    subject = "[SYNTHETIC] all-tools " + run_id
    token_handles = {}
    try:
        for name in ["alice", "bob"]:
            token_handles[name] = oauth_login(name, keys[name])
            clients[name] = httpx.Client(
                base_url=BASE, headers={"Authorization": "Bearer " + keys[name]}, timeout=60
            )
            catalogue = checked(
                clients[name].get("/mcp-rest/tools/list", params={"server_id": "outlook_lab"})
            )
            assert {t["name"] for t in catalogue["tools"]} == TOOLS, (
                "New/missing tools require explicit coverage"
            )
            runner.call(
                clients[name],
                "whoami",
                check=lambda v, n=name: v["mailbox"] == n + "@lab.example" and v["backend"] == "demo",
                case=name + ": OAuth subject and backend",
            )
            runner.call(
                clients[name],
                "list_folders",
                check=lambda v: {f["name"] for f in v} == {"inbox", "sent", "drafts", "trash"},
                case=name + ": folders",
            )
        alice, bob = clients["alice"], clients["bob"]
        mail_id = "welcome-alice@lab.example"
        runner.call(
            alice,
            "search_emails",
            {"query": "Стенд Outlook", "limit": 1},
            check=lambda v: len(v) == 1 and v[0]["id"] == mail_id,
            case="text query, limit and own mailbox",
        )
        runner.call(
            alice,
            "search_emails",
            {"query": run_id + "-absent"},
            check=lambda v: v == [],
            case="empty search",
        )
        runner.call(alice, "search_emails", {"limit": 101}, denied=True, case="limit above 100 rejected")
        message = runner.call(
            alice,
            "get_email",
            {"message_id": mail_id},
            check=lambda v: v["to"] == ["alice@lab.example"] and v["synthetic"] and bool(v["body"]),
            case="full owned message",
        )
        assert message["attachments"][0]["name"] == "stand-note.txt"
        attachment = runner.call(
            alice,
            "get_attachment",
            {"message_id": mail_id, "name": "stand-note.txt"},
            check=lambda v: v["synthetic"] is True,
            case="attachment bytes",
        )
        expected_bytes = b"Synthetic attachment for alice@lab.example\n"
        assert base64.b64decode(attachment["content_base64"], validate=True) == expected_bytes
        runner.call(
            alice,
            "get_attachment",
            {"message_id": mail_id, "name": "absent.txt"},
            denied=True,
            case="missing attachment rejected",
        )
        runner.call(
            alice,
            "get_email",
            {"message_id": "absent-" + run_id},
            denied=True,
            case="missing message rejected",
        )
        runner.call(
            alice,
            "get_email",
            {"message_id": mail_id, "folder": "sent"},
            denied=True,
            case="wrong folder rejected",
        )
        runner.call(
            alice,
            "whoami",
            {"mailbox": "bob@lab.example"},
            denied=True,
            case="mailbox argument injection rejected",
        )
        runner.call(alice, "mark_email_read", {"message_id": mail_id, "is_read": True}, case="mark read")
        runner.call(
            alice,
            "get_email",
            {"message_id": mail_id},
            check=lambda v: v["is_read"] is True,
            case="read flag persisted",
        )
        runner.call(alice, "mark_email_read", {"message_id": mail_id, "is_read": False}, case="mark unread")
        runner.call(
            alice,
            "get_email",
            {"message_id": mail_id},
            check=lambda v: v["is_read"] is False,
            case="unread flag persisted",
        )
        for tool, args in [
            ("get_email", {"message_id": mail_id}),
            ("get_attachment", {"message_id": mail_id, "name": "stand-note.txt"}),
            ("mark_email_read", {"message_id": mail_id}),
            ("move_email", {"message_id": mail_id, "destination": "trash"}),
        ]:
            runner.call(bob, tool, args, denied=True, case="Bob cannot access Alice message")
        draft_args = {
            "to": ["bob@lab.example"],
            "cc": ["stand@lab.example"],
            "bcc": ["audit@lab.example"],
            "subject": subject,
            "body": "Synthetic body " + run_id,
        }
        draft = runner.call(
            alice,
            "save_draft",
            draft_args,
            check=lambda v: v["folder"] == "drafts",
            case="save unsent draft with cc/bcc",
        )
        draft_id = draft["id"]
        runner.call(
            alice,
            "get_email",
            {"message_id": draft_id, "folder": "drafts"},
            check=lambda v: (
                v["subject"] == subject
                and v["cc"] == ["stand@lab.example"]
                and v["bcc"] == ["audit@lab.example"]
            ),
            case="draft persisted with recipients",
        )
        runner.call(
            alice,
            "save_draft",
            draft_args | {"to": ["invalid"]},
            denied=True,
            case="invalid recipient rejected",
        )
        runner.call(
            alice, "save_draft", draft_args | {"to": []}, denied=True, case="empty recipient list rejected"
        )
        runner.call(alice, "send_draft", {"draft_id": draft_id}, denied=True, case="confirmation required")
        runner.call(
            bob,
            "send_draft",
            {"draft_id": draft_id, "confirm": True},
            denied=True,
            case="Bob cannot send Alice draft",
        )
        runner.call(
            alice,
            "send_draft",
            {"draft_id": draft_id, "confirm": True},
            check=lambda v: v["status"] == "sent" and v["synthetic"],
            case="confirmed synthetic send",
        )
        runner.call(
            alice,
            "send_draft",
            {"draft_id": draft_id, "confirm": True},
            denied=True,
            case="already sent draft cannot be sent again",
        )
        runner.call(
            alice,
            "get_email",
            {"message_id": draft_id, "folder": "sent"},
            check=lambda v: v["subject"] == subject,
            case="sent item persisted",
        )
        runner.call(
            alice,
            "move_email",
            {"message_id": draft_id, "folder": "sent", "destination": "trash"},
            check=lambda v: v["destination"] == "trash",
            case="recoverable deletion",
        )
        runner.call(
            alice,
            "get_email",
            {"message_id": draft_id, "folder": "trash"},
            check=lambda v: v["folder"] == "trash",
            case="item found in trash",
        )
        runner.call(
            alice,
            "move_email",
            {"message_id": draft_id, "folder": "trash", "destination": "sent"},
            case="restore from trash",
        )
        runner.call(
            alice,
            "move_email",
            {"message_id": draft_id, "folder": "sent", "destination": "drafts"},
            denied=True,
            case="cannot convert sent message to draft",
        )
        runner.call(
            alice,
            "search_contacts",
            {"query": "stand", "limit": 1},
            check=lambda v: len(v) == 1 and v[0]["email"] == "stand@lab.example",
            case="directory query and limit",
        )
        runner.call(
            alice,
            "search_contacts",
            {"query": "absent-" + run_id},
            check=lambda v: v == [],
            case="empty directory search",
        )
        event = runner.call(
            alice,
            "save_event",
            INTERVAL | {"subject": subject, "location": "Synthetic room"},
            check=lambda v: v["synthetic"] and v["location"] == "Synthetic room",
            case="personal event without invitation",
        )
        runner.call(
            alice,
            "list_events",
            INTERVAL | {"limit": 100},
            check=lambda v: any(e["id"] == event["id"] and e["subject"] == subject for e in v),
            case="saved event appears in own calendar",
        )
        runner.call(
            alice,
            "list_events",
            {"start": "2026-11-02T10:00:00+03:00", "end": "2026-11-02T10:30:00+03:00"},
            check=lambda v: any(e["id"] == event["id"] for e in v),
            case="overlapping interval",
        )
        runner.call(
            alice,
            "list_events",
            {"start": "2027-01-01T00:00:00Z", "end": "2027-01-02T00:00:00Z"},
            check=lambda v: v == [],
            case="non-overlapping interval",
        )
        runner.call(
            bob,
            "list_events",
            INTERVAL,
            check=lambda v: not any(e["id"] == event["id"] for e in v),
            case="Bob calendar does not reveal Alice event",
        )
        runner.call(
            alice,
            "save_event",
            INTERVAL | {"subject": subject, "end": INTERVAL["start"]},
            denied=True,
            case="zero duration rejected",
        )
        runner.call(
            alice,
            "list_events",
            {"start": "2026-11-02T09:00:00", "end": "2026-11-02T11:00:00"},
            denied=True,
            case="timezone required",
        )
        # Genuine narrow-scope Keycloak token, acquired through the same LiteLLM OAuth route.
        oauth_login("alice", keys["alice"], scope="openid")
        runner.call(
            alice,
            "whoami",
            check=lambda v: v["scopes"] == ["openid"],
            case="access token has no operation scopes",
        )
        scope_args = {
            "list_folders": {},
            "search_emails": {},
            "get_email": {"message_id": mail_id},
            "get_attachment": {"message_id": mail_id, "name": "stand-note.txt"},
            "save_draft": draft_args,
            "send_draft": {"draft_id": draft_id, "confirm": True},
            "mark_email_read": {"message_id": mail_id},
            "move_email": {"message_id": draft_id, "folder": "sent", "destination": "trash"},
            "search_contacts": {"query": "stand"},
            "list_events": INTERVAL,
            "save_event": INTERVAL | {"subject": subject},
        }
        for tool, args in scope_args.items():
            runner.call(alice, tool, args, denied=True, case="real OAuth token missing operation scope")
        oauth_login("alice", keys["alice"], scope="openid outlook.read")
        runner.call(
            alice,
            "get_email",
            {"message_id": mail_id},
            check=lambda v: v["id"] == mail_id,
            case="read-only token can read",
        )
        runner.call(alice, "save_draft", draft_args, denied=True, case="read-only token cannot write")
        runner.call(
            alice,
            "send_draft",
            {"draft_id": draft_id, "confirm": True},
            denied=True,
            case="read-only token cannot send",
        )
        oauth_login("alice", keys["alice"])
        runner.call(
            alice, "whoami", check=lambda v: "outlook.send" in v["scopes"], case="full lab access restored"
        )
        assert all(row["positive"] > 0 for row in runner.tools.values()), (
            "Not every tool passed a success path"
        )
        report = {
            "status": "PASS",
            "time_moscow": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(),
            "gateway": BASE,
            "server_id": "outlook_lab",
            "backend": "demo",
            "exchange_verified": False,
            "oauth": "MCP confidential client at Keycloak; authorization_code + S256 PKCE; LiteLLM stores MCP-issued tokens",
            "tool_count": len(TOOLS),
            "call_count": len(runner.calls),
            "positive_calls": sum(v["positive"] for v in runner.tools.values()),
            "negative_calls": sum(v["negative"] for v in runner.tools.values()),
            "attachment_sha256": hashlib.sha256(expected_bytes).hexdigest(),
            "tools": runner.tools,
            "calls": runner.calls,
        }
        (ROOT / "docs/all-tools-results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps(
                {k: v for k, v in report.items() if k not in ["calls", "tools"]}, ensure_ascii=False, indent=2
            )
        )
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    main()
