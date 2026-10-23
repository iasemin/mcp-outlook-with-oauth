import json
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OUTLOOK_", extra="ignore")
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
