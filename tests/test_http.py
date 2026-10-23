import json
import time
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from outlook_mcp.config import Settings
from outlook_mcp.server import create_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def setup(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    mapping = tmp_path / "mailboxes.json"
    mapping.write_text(json.dumps({"alice-id": "alice@lab.example", "bob-id": "bob@lab.example"}))
    settings = Settings(
        backend="demo",
        issuer="https://issuer.example/realms/test",
        public_key=public.decode(),
        mapping_file=Path(mapping),
    )
    app = create_server(settings).http_app(stateless_http=True, json_response=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost:8766"
        ) as client:
            yield client, private


def token(private, **overrides):
    claims = {
        "iss": "https://issuer.example/realms/test",
        "aud": "outlook-mcp",
        "sub": "alice-id",
        "typ": "Bearer",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "scope": "outlook.read outlook.write outlook.send calendar.read calendar.write contacts.read",
    }
    return jwt.encode(claims | overrides, private, algorithm="RS256")


async def call(client, bearer, name="whoami", args=None):
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    return await client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args or {}},
        },
    )


async def test_no_token_rejected_with_resource_discovery(setup):
    client, _ = setup
    response = await call(client, None)
    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]
    import re

    metadata = re.search(r'resource_metadata="([^"]+)"', response.headers["www-authenticate"]).group(1)
    discovery = await client.get(metadata)
    assert discovery.status_code == 200
    assert discovery.json()["resource"] == "http://localhost:8766/mcp"
    assert discovery.json()["authorization_servers"] == ["https://issuer.example/realms/test"]


@pytest.mark.parametrize(
    "override",
    [
        {"aud": "some-other-api"},
        {"exp": 1},
        {"iss": "https://attacker.example"},
        {"exp": None},
        {"nbf": 9999999999},
        {"typ": "ID"},
    ],
)
async def test_invalid_tokens_rejected(setup, override):
    client, private = setup
    assert (await call(client, token(private, **override))).status_code == 401


async def test_wrong_signature_rejected(setup):
    client, _ = setup
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert (await call(client, token(other_key))).status_code == 401


async def test_valid_user_and_cross_mailbox_access(setup):
    client, private = setup
    a = token(private, email="bob@lab.example")
    result = (await call(client, a)).json()["result"]
    assert result["structuredContent"]["mailbox"] == "alice@lab.example"
    assert result["structuredContent"]["backend"] == "demo"
    forbidden = (await call(client, a, "get_email", {"message_id": "welcome-bob@lab.example"})).json()
    assert forbidden["result"]["isError"] is True


async def test_readonly_token_cannot_write(setup):
    client, private = setup
    response = await call(
        client,
        token(private, scope="outlook.read"),
        "save_draft",
        {"to": ["bob@lab.example"], "subject": "Test", "body": "Body"},
    )
    assert response.json()["result"]["isError"] is True


async def test_health_does_not_claim_exchange_is_connected(setup):
    client, _ = setup
    result = (await client.get("/healthz")).json()
    assert result == {"status": "ok", "backend": "demo", "exchange_verified": False}
