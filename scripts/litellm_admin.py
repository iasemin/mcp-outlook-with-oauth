"""Read the already-running proxy's configured admin key without displaying or duplicating it."""

import json
import os
import subprocess

import httpx

CONTAINER = os.environ.get("LITELLM_CONTAINER", "litellm_guardrails-litellm-1")
BASE = os.environ.get("LITELLM_URL", "http://localhost:8400")


def admin_client():
    # Captured stdout remains in memory; never print the result or a full HTTP error response.
    code = """import os,yaml
c=yaml.safe_load(open('/app/config.yaml'))
v=c.get('general_settings',{}).get('master_key') or os.environ.get('LITELLM_MASTER_KEY')
if v and v.startswith('os.environ/'):
 v=os.environ[v.split('/',1)[1]]
assert v, 'No configured admin key found'
print(v,end='')"""
    key = subprocess.check_output(["docker", "exec", CONTAINER, "python", "-c", code], text=True)
    return httpx.Client(base_url=BASE, headers={"Authorization": "Bearer " + key}, timeout=60)


def checked(response):
    if response.status_code >= 400:
        # Avoid exposing server-returned credentials or token-bearing URLs in exceptions.
        raise RuntimeError(
            f"LiteLLM API request failed: HTTP {response.status_code} {response.request.url.path}"
        )
    return response.json()


if __name__ == "__main__":
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    creds = json.loads((root / ".local/credentials.json").read_text())
    with admin_client() as client:
        payload = {
            "server_id": "outlook_lab",
            "server_name": "outlook_lab",
            "alias": "outlook_lab",
            "description": "Local OAuth2 Keycloak mail stand. SYNTHETIC data; not a live Exchange connection.",
            "url": "http://outlook-mcp:8766/mcp",
            "transport": "http",
            "auth_type": "oauth2",
            "oauth2_flow": "authorization_code",
            # Split browser and Docker endpoint addresses. An explicit issuer in LiteLLM 1.96
            # takes precedence over manual URLs and tries localhost inside its container.
            # MCP itself always verifies the canonical Keycloak issuer and audience.
            "issuer": None,
            "authorization_url": "http://localhost:8800/realms/outlook-lab/protocol/openid-connect/auth",
            "token_url": "http://outlook-keycloak:8080/realms/outlook-lab/protocol/openid-connect/token",
            "credentials": {
                "client_id": "outlook-litellm",
                "client_secret": creds["client"],
                "scopes": [
                    "openid",
                    "outlook.read",
                    "outlook.write",
                    "outlook.send",
                    "calendar.read",
                    "calendar.write",
                    "contacts.read",
                ],
            },
            "available_on_public_internet": False,
            "allow_all_keys": False,
        }
        existing = client.get("/v1/mcp/server/outlook_lab")
        if existing.status_code == 404:
            checked(client.post("/v1/mcp/server", json=payload))
        else:
            previous = checked(existing)
            if previous.get("issuer"):
                # Clearing issuer intentionally clears resolved endpoints in 1.96.0.
                checked(client.put("/v1/mcp/server", json={"server_id": "outlook_lab", "issuer": None}))
            checked(client.put("/v1/mcp/server", json=payload))
        print("Registered outlook_lab (OAuth2 authorization_code) in existing LiteLLM. Secrets not printed.")
