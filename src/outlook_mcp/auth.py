"""Signature validation stays in FastMCP; enforce mandatory access-token semantics here."""

import time

from fastmcp.server.auth.providers.jwt import JWTVerifier


class AccessTokenVerifier(JWTVerifier):
    async def verify_token(self, token: str):
        if len(token) > 16384:
            return None
        validated = await super().verify_token(token)
        if validated is None:
            return None
        claims = validated.claims
        now = time.time()
        if claims.get("typ") != "Bearer" or not isinstance(claims.get("sub"), str):
            return None
        exp = claims.get("exp")
        if type(exp) not in (int, float) or not now < exp:
            return None
        for name in ("nbf", "iat"):
            value = claims.get(name)
            if value is not None and (type(value) not in (int, float) or value > now + 5):
                return None
        return validated


def build_auth(settings, scopes):
    """MCP owns the upstream confidential client; LiteLLM gets separate MCP tokens."""
    import base64
    import hashlib

    from cryptography.fernet import Fernet
    from fastmcp.server.auth import RemoteAuthProvider
    from key_value.aio.stores.filetree import FileTreeStore
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    from .oauth_proxy import StrictOAuthProxy

    verifier = AccessTokenVerifier(
        public_key=settings.public_key,
        jwks_uri=settings.jwks_uri,
        issuer=settings.issuer,
        audience=settings.audience,
        algorithm="RS256",
    )
    if settings.auth_mode == "resource":
        return RemoteAuthProvider(
            token_verifier=verifier,
            authorization_servers=[settings.issuer],
            base_url=settings.public_url,
            resource_base_url=settings.public_url,
            scopes_supported=scopes,
            resource_name="Outlook Exchange MCP",
        )
    signing_key = settings.oauth_signing_key_file.read_text().strip()
    # Domain-separated encryption key, stable across upstream client secret rotation.
    encryption_key = base64.urlsafe_b64encode(
        hashlib.sha256(b"outlook-mcp-storage-v1:" + signing_key.encode()).digest()
    )
    settings.oauth_storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = FernetEncryptionWrapper(
        key_value=FileTreeStore(data_directory=settings.oauth_storage_dir),
        fernet=Fernet(encryption_key),
    )
    return StrictOAuthProxy(
        upstream_authorization_endpoint=settings.authorization_endpoint,
        upstream_token_endpoint=settings.token_endpoint,
        upstream_client_id=settings.oauth_client_id,
        upstream_client_secret=settings.oauth_client_secret_file.read_text().strip(),
        token_endpoint_auth_method=settings.token_endpoint_auth_method,
        token_verifier=verifier,
        base_url=settings.public_url,
        redirect_path="/auth/callback",
        valid_scopes=["openid", *scopes],
        allowed_client_redirect_uris=settings.client_redirect_uris,
        forward_pkce=True,
        forward_resource=False,
        client_storage=store,
        jwt_signing_key=signing_key,
        require_authorization_consent=True,
        enable_cimd=False,
    )
