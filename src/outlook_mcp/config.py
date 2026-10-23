import json
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OUTLOOK_", extra="ignore")
    auth_mode: Literal["proxy", "resource"] = "proxy"
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret_file: Path | None = None
    oauth_signing_key_file: Path | None = None
    oauth_storage_dir: Path = Path("/var/lib/outlook-mcp/oauth")
    client_redirect_uris: list[str] = []
    token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_basic"
    backend: Literal["demo", "ews"] = "ews"
    issuer: str
    audience: str = "outlook-mcp"
    jwks_uri: str | None = None
    public_key: str | None = None
    public_url: str = "http://localhost:8766"
    mapping_file: Path
    ews_endpoint: str | None = None
    ews_username: str | None = None
    ews_password_file: Path | None = None
    ews_password: SecretStr | None = Field(default=None, repr=False)
    port: int = 8766

    @model_validator(mode="after")
    def check(self):
        if not self.public_key and not self.jwks_uri:
            raise ValueError("JWKS URI or public key is required")
        if self.auth_mode == "proxy":
            if not all(
                (
                    self.authorization_endpoint,
                    self.token_endpoint,
                    self.oauth_client_id,
                    self.oauth_client_secret_file,
                    self.oauth_signing_key_file,
                    self.client_redirect_uris,
                )
            ):
                raise ValueError(
                    "OAuth proxy requires AAS endpoints, client ID, secret/signing files and redirect URIs"
                )
            from urllib.parse import urlparse

            for url in [
                self.public_url,
                self.issuer,
                self.authorization_endpoint,
                self.token_endpoint,
                *self.client_redirect_uris,
            ]:
                parsed = urlparse(url)
                if parsed.scheme != "https" and not (self.backend == "demo" and parsed.scheme == "http"):
                    raise ValueError("OAuth proxy requires HTTPS (HTTP is allowed only for synthetic demo)")
                if not parsed.netloc or parsed.fragment or parsed.username or "*" in url:
                    raise ValueError(
                        "OAuth URLs must be absolute and cannot contain wildcards, userinfo or fragments"
                    )
            if len(self.oauth_signing_key_file.read_text().strip()) < 32:
                raise ValueError("OAuth signing key requires at least 32 characters")
            if not self.oauth_client_secret_file.read_text().strip():
                raise ValueError("OAuth client secret cannot be empty")
        if self.backend == "ews":
            if not self.ews_endpoint or not self.ews_endpoint.startswith("https://"):
                raise ValueError("EWS requires an HTTPS endpoint")
            if not self.ews_username or not (self.ews_password_file or self.ews_password):
                raise ValueError("EWS service credentials are required")
        return self

    def mapping(self) -> dict[str, str]:
        value = json.loads(self.mapping_file.read_text())
        if not isinstance(value, dict) or not value:
            raise ValueError("Mailbox mapping must be a non-empty object")
        for subject, mailbox in value.items():
            if (
                not isinstance(subject, str)
                or not subject
                or not isinstance(mailbox, str)
                or "@" not in mailbox
            ):
                raise ValueError("Invalid mailbox mapping")
        return value

    def password(self) -> str:
        if self.ews_password_file:
            return self.ews_password_file.read_text().rstrip("\r\n")
        return self.ews_password.get_secret_value() if self.ews_password else ""
