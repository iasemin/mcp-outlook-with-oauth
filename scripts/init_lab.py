"""Create ignored local-only credentials and a reproducible Keycloak import."""

import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ["outlook.read", "outlook.write", "outlook.send", "calendar.read", "calendar.write", "contacts.read"]
USERS = {"alice": "11111111-1111-4111-8111-111111111111", "bob": "22222222-2222-4222-8222-222222222222"}


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(value)


def main():
    secrets_path = ROOT / ".local/credentials.json"
    if secrets_path.exists():
        credentials = json.loads(secrets_path.read_text())
    else:
        credentials = {
            key: secrets.token_urlsafe(32) for key in ["postgres", "admin", "client", "alice", "bob"]
        }
        private_write(secrets_path, json.dumps(credentials, indent=2))
    if "signing" not in credentials:
        credentials["signing"] = secrets.token_urlsafe(48)
        private_write(secrets_path, json.dumps(credentials, indent=2))
    # Files live inside a private host directory; non-root container UID reads the mounts.
    for filename, value in [
        ("aas-client-secret", credentials["client"]),
        ("oauth-signing-key", credentials["signing"]),
    ]:
        private_write(ROOT / ".local" / filename, value)
        (ROOT / ".local" / filename).chmod(0o644)
    realm = {
        "realm": "outlook-lab",
        "enabled": True,
        "sslRequired": "none",
        "registrationAllowed": False,
        "editUsernameAllowed": False,
        "resetPasswordAllowed": False,
        "accessTokenLifespan": 45,
        "ssoSessionIdleTimeout": 1800,
        "clientScopes": [
            {"name": scope, "protocol": "openid-connect", "attributes": {"include.in.token.scope": "true"}}
            for scope in SCOPES
        ],
        "clients": [
            {
                "clientId": "outlook-mcp",
                "name": "Outlook MCP OAuth client",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "secret": credentials["client"],
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False,
                "redirectUris": ["http://localhost:8766/auth/callback"],
                "webOrigins": [],
                "defaultClientScopes": [],
                "optionalClientScopes": SCOPES,
                "attributes": {"pkce.code.challenge.method": "S256"},
                "protocolMappers": [
                    {
                        "name": "stable-subject",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-sub-mapper",
                        "config": {"access.token.claim": "true", "introspection.token.claim": "true"},
                    },
                    {
                        "name": "outlook-audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "config": {
                            "included.custom.audience": "outlook-mcp",
                            "access.token.claim": "true",
                            "id.token.claim": "false",
                        },
                    },
                ],
            }
        ],
        "users": [
            {
                "id": subject,
                "username": name,
                "enabled": True,
                "emailVerified": True,
                "email": name + "@lab.example",
                "firstName": name.title(),
                "lastName": "Lab",
                "credentials": [{"type": "password", "value": credentials[name], "temporary": False}],
                "requiredActions": [],
            }
            for name, subject in USERS.items()
        ],
    }
    private_write(ROOT / ".local/keycloak-realm.json", json.dumps(realm, indent=2))
    private_write(
        ROOT / ".local/mailboxes.json",
        json.dumps({sub: name + "@lab.example" for name, sub in USERS.items()}),
    )
    (ROOT / ".local").chmod(0o700)
    # The enclosing directory is private on the host; container UIDs need read access to these bind mounts.
    (ROOT / ".local/keycloak-realm.json").chmod(0o644)
    (ROOT / ".local/mailboxes.json").chmod(0o644)
    private_write(
        ROOT / ".env",
        "\n".join(
            [
                "LAB_POSTGRES_PASSWORD=" + credentials["postgres"],
                "LAB_ADMIN_PASSWORD=" + credentials["admin"],
                "LITELLM_NETWORK=litellm_guardrails_default",
                "",
            ]
        ),
    )
    print("Local credentials, mailbox mapping and realm import generated (secrets not printed).")


if __name__ == "__main__":
    main()
