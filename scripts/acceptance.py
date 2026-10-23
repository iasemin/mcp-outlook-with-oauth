"""Live acceptance: browser-style OAuth PKCE via existing LiteLLM, no password grant.

Only generated local lab users are signed in. Tokens and keys never appear in output.
"""

import base64
import hashlib
import json
import secrets
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from litellm_admin import BASE, admin_client, checked

ROOT = Path(__file__).resolve().parents[1]
CREDS = json.loads((ROOT / ".local/credentials.json").read_text())


class ConsentForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action")


def oauth_login(username, key, scope=None, *, invalid_verifier=False):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(24)
    with httpx.Client(timeout=30) as browser:
        response = browser.get(
            BASE + "/outlook_lab/authorize",
            params={
                "client_id": "outlook_lab",
                "redirect_uri": "http://localhost:8899/callback",
                "response_type": "code",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": scope
                if scope is not None
                else "openid outlook.read outlook.write outlook.send calendar.read calendar.write contacts.read",
            },
        )
        assert response.status_code in (302, 307), f"Authorize failed: {response.status_code}"
        consent_url = response.headers["location"]
        consent = browser.get(consent_url, follow_redirects=True)
        assert consent.status_code == 200 and "/consent" in str(consent.url), "MCP consent not found"
        form = ConsentForm()
        form.feed(consent.text)
        assert form.fields.get("csrf_token"), "MCP consent CSRF missing"
        approved = browser.post(str(consent.url), data=form.fields | {"action": "approve"})
        assert approved.status_code in (302, 303, 307), "MCP consent failed"
        upstream = parse_qs(urlparse(approved.headers["location"]).query)
        assert upstream["client_id"] == ["outlook-mcp"], "MCP is not the AAS OAuth client"
        assert upstream["redirect_uri"] == ["http://localhost:8766/auth/callback"]
        assert upstream["code_challenge_method"] == ["S256"]
        login = browser.get(approved.headers["location"])
        form = LoginForm()
        form.feed(login.text)
        assert form.action, "Keycloak login form not found"
        # Browsers treat localhost as a trustworthy origin and send Keycloak's Secure
        # cookies there even on HTTP. Python CookieJar does not implement that exception.
        assert urlparse(form.action).hostname == "localhost"
        for cookie in browser.cookies.jar:
            if cookie.name.startswith(("AUTH_SESSION_ID", "KC_")):
                cookie.secure = False
        response = browser.post(
            form.action, data={"username": username, "password": CREDS[username], "credentialId": ""}
        )
        assert response.status_code in (302, 303), f"Keycloak sign-in failed: {response.status_code}"
        mcp_callback = browser.get(response.headers["location"])
        assert mcp_callback.status_code in (302, 303, 307), "MCP upstream code exchange failed"
        callback = browser.get(mcp_callback.headers["location"])
        assert callback.status_code in (302, 307), f"LiteLLM callback failed: {callback.status_code}"
        params = parse_qs(urlparse(callback.headers["location"]).query)
        assert params.get("state") == [state], "OAuth state mismatch"
        code = params["code"][0]
        response = browser.post(
            BASE + "/outlook_lab/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "outlook_lab",
                "redirect_uri": "http://localhost:8899/callback",
                "code_verifier": "wrong-" + verifier if invalid_verifier else verifier,
            },
            headers={"x-litellm-api-key": "Bearer " + key},
        )
        if invalid_verifier:
            assert response.status_code == 400, "Incorrect PKCE verifier was accepted"
            return None
        assert response.status_code == 200, f"LiteLLM code exchange failed: {response.status_code}"
        result = response.json()
        assert result.get("access_token") and result.get("refresh_token"), "No OAuth tokens returned"
        return result


def gateway_call(client, name, arguments=None):
    result = checked(
        client.post(
            "/mcp-rest/tools/call",
            json={"server_id": "outlook_lab", "name": name, "arguments": arguments or {}},
        )
    )
    return result


def content(result):
    if result.get("structuredContent") is not None:
        value = result["structuredContent"]
        return value.get("result", value) if isinstance(value, dict) else value
    if "result" in result:
        return content(result["result"])
    for entry in result.get("content", []):
        if entry.get("type") == "text":
            return json.loads(entry["text"])
    raise AssertionError("Unexpected tool response shape: " + str(list(result)))


def main():
    report = {
        "gateway": BASE,
        "backend": "demo",
        "exchange_verified": False,
        "oauth_client": "MCP (outlook-mcp)",
        "checks": [],
    }
    key_path = ROOT / ".local/litellm-user-keys.json"
    keys = json.loads(key_path.read_text()) if key_path.exists() else {}
    with admin_client() as admin:
        for name in ["alice", "bob"]:
            if name not in keys:
                user_id = "outlook-lab-" + name
                response = admin.post(
                    "/user/new",
                    json={
                        "user_id": user_id,
                        "user_email": name + "@lab.example",
                        "user_role": "internal_user",
                        "auto_create_key": False,
                    },
                )
                assert response.status_code in (200, 400), f"User setup failed: {response.status_code}"
                result = checked(
                    admin.post(
                        "/key/generate",
                        json={
                            "user_id": user_id,
                            "key_alias": "outlook-lab-" + name,
                            "object_permission": {"mcp_servers": ["outlook_lab"]},
                            "models": [],
                        },
                    )
                )
                keys[name] = result["key"]
                from init_lab import private_write

                private_write(key_path, json.dumps(keys))
            checked(
                admin.post(
                    "/key/update",
                    json={"key": keys[name], "object_permission": {"mcp_servers": ["outlook_lab"]}},
                )
            )
    tokens = {}
    clients = {}
    try:
        for name in ["alice", "bob"]:
            tokens[name] = oauth_login(name, keys[name])
            clients[name] = httpx.Client(
                base_url=BASE, headers={"Authorization": "Bearer " + keys[name]}, timeout=60
            )
            status = checked(clients[name].get("/v1/mcp/server/outlook_lab/oauth-user-credential/status"))
            assert status["has_credential"], "LiteLLM did not persist per-user OAuth token"
            catalogue = checked(
                clients[name].get("/mcp-rest/tools/list", params={"server_id": "outlook_lab"})
            )
            assert any(t["name"] == "whoami" for t in catalogue["tools"]), "Authenticated catalog missing"
            me = content(gateway_call(clients[name], "whoami"))
            assert me["mailbox"] == name + "@lab.example", "Incorrect identity through gateway"
            mail = content(gateway_call(clients[name], "search_emails"))
            assert len(mail) == 1 and mail[0]["to"] == [name + "@lab.example"]
            assert mail[0]["synthetic"] is True
            report["checks"].append(name + ": PKCE login, stored per-user token, owned mail read via LiteLLM")
        foreign = gateway_call(clients["alice"], "get_email", {"message_id": "welcome-bob@lab.example"})
        assert foreign.get("isError") or foreign.get("result", {}).get("isError"), (
            "Cross-mailbox access not denied"
        )
        report["checks"].append("Alice cannot read Bob message ID through LiteLLM")
        draft = content(
            gateway_call(
                clients["alice"],
                "save_draft",
                {
                    "to": ["bob@lab.example"],
                    "subject": "[SYNTHETIC] OAuth acceptance",
                    "body": "Synthetic body",
                },
            )
        )
        denied = gateway_call(clients["bob"], "send_draft", {"draft_id": draft["id"], "confirm": True})
        assert denied.get("isError") or denied.get("result", {}).get("isError"), (
            "Foreign draft send not denied"
        )
        sent = content(
            gateway_call(clients["alice"], "send_draft", {"draft_id": draft["id"], "confirm": True})
        )
        assert sent["status"] == "sent" and sent["synthetic"]
        report["checks"].append("Synthetic draft save/send; Bob cannot send Alice draft")
        expiry_wait = tokens["alice"]["expires_in"] + 2
        assert expiry_wait <= 60, "Lab token TTL must be <=58 seconds for the lifecycle test"
        print(
            f"PKCE and isolation passed. Waiting {expiry_wait}s to test expiry and automatic gateway refresh.",
            flush=True,
        )
        time.sleep(expiry_wait)
        with httpx.Client(timeout=30) as direct:
            old = direct.post(
                "http://localhost:8766/mcp",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer " + tokens["alice"]["access_token"],
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert old.status_code == 401, "Expired MCP access token was accepted"
        assert content(gateway_call(clients["alice"], "whoami"))["mailbox"] == "alice@lab.example"
        report["checks"].append(
            "Expired MCP token rejected; LiteLLM refreshes at MCP, MCP refreshes at Keycloak"
        )
        # LiteLLM proactively refreshes short-lived tokens; the original refresh token
        # has already been rotated. Use a fresh login for an independent explicit grant.
        explicit = oauth_login("alice", keys["alice"])
        with httpx.Client(timeout=30) as client:
            response = client.post(
                BASE + "/outlook_lab/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": explicit["refresh_token"],
                    "client_id": "outlook_lab",
                },
                headers={"x-litellm-api-key": "Bearer " + keys["alice"]},
            )
            assert response.status_code == 200 and response.json().get("access_token"), "OAuth refresh failed"
            replay = client.post(
                BASE + "/outlook_lab/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": explicit["refresh_token"],
                    "client_id": "outlook_lab",
                },
                headers={"x-litellm-api-key": "Bearer " + keys["alice"]},
            )
            assert replay.status_code == 400, "Used refresh token was accepted twice"

            headers = {"Accept": "application/json, text/event-stream"}
            response = client.post(
                "http://localhost:8766/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert response.status_code == 401
            response = client.post(
                "http://localhost:8766/mcp",
                headers=headers | {"Authorization": "Bearer invalid"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert response.status_code == 401
        report["checks"].extend(
            [
                "Refresh via LiteLLM -> MCP -> Keycloak; rotated refresh token replay rejected",
                "Missing/malformed token rejected by MCP",
            ]
        )
        oauth_login("alice", keys["alice"], invalid_verifier=True)
        report["checks"].append("Incorrect downstream PKCE verifier rejected")
        tools = checked(clients["alice"].get("/mcp-rest/tools/list", params={"server_id": "outlook_lab"}))
        report["tool_count"] = len(tools["tools"])
        report["status"] = "PASS"
        (ROOT / ".local/acceptance.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    main()
