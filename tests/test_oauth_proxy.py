"""MCP is the upstream confidential client, independently of LiteLLM registration."""

import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from outlook_mcp.config import Settings
from outlook_mcp.server import create_server


@pytest.fixture
def proxy_settings(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "private.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"alice": "alice@lab.example"}))
    secret = tmp_path / "aas-secret"
    secret.write_text("test-only-upstream-secret-123456789")
    signing = tmp_path / "signing-key"
    signing.write_text("test-only-signing-material-123456789")
    return dict(
        backend="demo",
        issuer="https://aas.example",
        public_key=public,
        mapping_file=mapping,
        authorization_endpoint="https://aas.example/authorize",
        token_endpoint="https://aas.example/token",
        oauth_client_id="outlook-mcp",
        oauth_client_secret_file=secret,
        oauth_signing_key_file=signing,
        oauth_storage_dir=tmp_path / "state",
        client_redirect_uris=["http://localhost:8899/callback"],
    )


def test_default_requires_mcp_oauth_client_configuration(proxy_settings):
    incomplete = {k: v for k, v in proxy_settings.items() if k != "oauth_client_id"}
    with pytest.raises(ValidationError, match="OAuth proxy"):
        Settings(**incomplete)


@pytest.mark.asyncio
async def test_discovery_registration_and_untrusted_redirect(proxy_settings):
    settings = Settings(**proxy_settings)
    assert settings.auth_mode == "proxy"
    app = create_server(settings).http_app(stateless_http=True, json_response=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost:8766"
        ) as client:
            metadata = await client.get("/.well-known/oauth-authorization-server")
            assert metadata.status_code == 200
            assert metadata.json()["authorization_endpoint"] == "http://localhost:8766/authorize"
            resource = await client.get("/.well-known/oauth-protected-resource/mcp")
            assert resource.json()["authorization_servers"] == ["http://localhost:8766/"]
            registration = await client.post(
                "/register",
                json={
                    "client_name": "LiteLLM test",
                    "redirect_uris": ["http://localhost:8899/callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                },
            )
            assert registration.status_code == 201
            info = registration.json()
            for requested_scope in ["outlook.read", "invalid.scope"]:
                bad_redirect = await client.get(
                    "/authorize",
                    params={
                        "client_id": info["client_id"],
                        "redirect_uri": "http://localhost:8899/callback?next=attacker",
                        "response_type": "code",
                        "scope": requested_scope,
                        "state": "test",
                        "code_challenge": "a" * 43,
                        "code_challenge_method": "S256",
                    },
                )
                assert bad_redirect.status_code == 400
                assert "location" not in bad_redirect.headers

            assert info["client_id"] != "outlook-mcp"
            rejected = await client.post(
                "/register",
                json={
                    "redirect_uris": ["https://attacker.example/callback"],
                    "token_endpoint_auth_method": "none",
                },
            )
            assert rejected.status_code == 400
            callback = await client.get("/auth/callback", params={"state": "forged", "code": "stolen"})
            assert callback.status_code == 400
            # AAS access tokens must not be accepted in place of the MCP-issued token.
            no_token = await client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream", "Authorization": "Bearer forged"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert no_token.status_code == 401
            upstream_token = jwt.encode(
                {
                    "iss": settings.issuer,
                    "aud": settings.audience,
                    "sub": "alice",
                    "typ": "Bearer",
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 300,
                    "scope": "outlook.read",
                },
                (settings.mapping_file.parent / "private.pem").read_bytes(),
                algorithm="RS256",
            )
            substituted = await client.post(
                "/mcp",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer " + upstream_token,
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert substituted.status_code == 401
            authorize = await client.get(
                "/authorize",
                params={
                    "client_id": info["client_id"],
                    "redirect_uri": "http://localhost:8899/callback",
                    "response_type": "code",
                    "scope": "outlook.read",
                    "state": "downstream-state",
                    "code_challenge": "a" * 43,
                    "code_challenge_method": "S256",
                },
            )
            assert authorize.status_code == 302
            consent = await client.get(authorize.headers["location"])
            from html.parser import HTMLParser

            class Inputs(HTMLParser):
                fields = None

                def handle_starttag(self, tag, attrs):
                    attrs = dict(attrs)
                    if tag == "input" and attrs.get("name"):
                        self.fields[attrs["name"]] = attrs.get("value", "")

            inputs = Inputs()
            inputs.fields = {}
            inputs.feed(consent.text)
            invalid_csrf = await client.post(
                str(consent.url),
                data=inputs.fields
                | {
                    "action": "approve",
                    "csrf_token": "forged",
                },
            )
            assert invalid_csrf.status_code == 400
            approved = await client.post(str(consent.url), data=inputs.fields | {"action": "approve"})
            assert approved.status_code == 302
            upstream = parse_qs(urlparse(approved.headers["location"]).query)
            assert upstream["client_id"] == ["outlook-mcp"]
            assert upstream["redirect_uri"] == ["http://localhost:8766/auth/callback"]
            assert upstream["code_challenge_method"] == ["S256"]
            assert upstream["code_challenge"] != ["a" * 43]
            assert upstream["state"] != ["downstream-state"]


@pytest.mark.asyncio
async def test_proxy_state_is_encrypted_and_persisted(proxy_settings):
    from outlook_mcp.auth import build_auth

    settings = Settings(**proxy_settings)
    first = build_auth(settings, ["outlook.read"])
    await first._client_storage.put(key="test", value={"token": "upstream-secret-marker"})
    second = build_auth(settings, ["outlook.read"])
    assert await second._client_storage.get(key="test") == {"token": "upstream-secret-marker"}
    for path in settings.oauth_storage_dir.rglob("*"):
        if path.is_file():
            assert b"upstream-secret-marker" not in path.read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "allowed,attempt",
    [
        (
            "https://litellm.example/callback?tenant=trusted",
            "https://litellm.example/callback?tenant=attacker",
        ),
        ("https://litellm.example/", "https://litellm.example/unapproved"),
        ("https://litellm.example/callback", "https://litellm.example/callback?next=attacker"),
    ],
)
async def test_redirect_allowlist_is_exact(proxy_settings, allowed, attempt):
    from mcp.server.auth.provider import AuthorizationParams, AuthorizeError, RegistrationError
    from mcp.shared.auth import OAuthClientInformationFull
    from pydantic import AnyUrl

    from outlook_mcp.auth import build_auth

    settings = Settings(**(proxy_settings | {"client_redirect_uris": [allowed]}))
    provider = build_auth(settings, ["outlook.read"])
    registered = OAuthClientInformationFull(client_id="downstream", redirect_uris=[AnyUrl(allowed)])
    await provider.register_client(registered)
    with pytest.raises(RegistrationError):
        await provider.register_client(
            OAuthClientInformationFull(client_id="unapproved", redirect_uris=[AnyUrl(attempt)])
        )
    with pytest.raises(AuthorizeError):
        await provider.authorize(
            registered,
            AuthorizationParams(
                redirect_uri=AnyUrl(attempt),
                redirect_uri_provided_explicitly=True,
                code_challenge="a" * 43,
                scopes=["outlook.read"],
                state="test",
            ),
        )
    assert await provider.get_client("outlook-mcp") is None
