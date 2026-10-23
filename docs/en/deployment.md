# Deployment and configuration

[Русский](../ru/deployment.md) · [Architecture](architecture.md)

## Build

```sh
git clone https://github.com/iasemin/mcp-outlook-with-oauth.git
cd mcp-outlook-with-oauth
docker buildx build --platform linux/amd64 \
  -t YOUR_REGISTRY/mcp-outlook-with-oauth:0.2.0 --push .
```

No prebuilt image is currently published. Choose the platform matching your Kubernetes nodes; an Apple Silicon default build is ARM64.

## Exchange prerequisites

Use two dedicated test mailboxes and a service AD account. In Exchange Management Shell, replace the example aliases/login and preview the scope before granting access:

```powershell
Get-ExchangeServer | Format-Table Name,AdminDisplayVersion
Get-WebServicesVirtualDirectory | Format-List Identity,InternalUrl,WindowsAuthentication,ExtendedProtectionTokenChecking
Get-CASMailbox mcp-test-a@corp.example | Format-List Ews*
New-ManagementScope -Name "OutlookMCP-TestMailboxes" -RecipientRestrictionFilter "(Alias -eq 'mcp-test-a') -or (Alias -eq 'mcp-test-b')"
Get-Recipient -Filter (Get-ManagementScope "OutlookMCP-TestMailboxes").RecipientFilter | Format-Table Alias,PrimarySmtpAddress
New-ManagementRoleAssignment -Name "OutlookMCP-TestImpersonation" -Role ApplicationImpersonation -User "CORP\svc-outlook-mcp" -CustomRecipientWriteScope "OutlookMCP-TestMailboxes"
```

The preview must contain only the intended mailboxes. Check that other assignments do not broaden service-account rights. Do not grant organization-wide impersonation. The current adapter requires EWS HTTPS + NTLM; an NTLM-prohibited environment needs a different adapter. Preserve TLS and Extended Protection, including the intended load-balancer configuration.

Record exact CU15/SU/HU build numbers and live results. [Microsoft: scoped impersonation](https://learn.microsoft.com/en-us/exchange/client-developer/exchange-web-services/how-to-configure-impersonation), [Extended Protection](https://learn.microsoft.com/en-us/exchange/plan-and-deploy/post-installation-tasks/security-best-practices/exchange-extended-protection).

## AAS (Keycloak in the lab), MCP and LiteLLM

**MCP itself is the AAS OAuth2 client.** Register a confidential `outlook-mcp` client; give its secret only to MCP:

- Authorization Code with S256 PKCE; callback `https://YOUR_MCP/auth/callback`.
- Access tokens need stable `sub`, expected `iss`, `aud=outlook-mcp`, `exp`, `typ=Bearer` and `scope`. The current verifier supports RS256 JWTs; opaque tokens or a different AAS contract require an adapter.
- Grant operation scopes under IdP policy. Lab Keycloak uses optional scopes and disables password grants.

MCP exposes `/.well-known/oauth-authorization-server`, `/register`, `/authorize`, `/token`, `/auth/callback` and `/mcp`. Route these paths, `/consent` and protected-resource discovery through ingress. MCP exchanges codes and refreshes upstream tokens itself. Users approve MCP consent and sign in at AAS; user passwords are entered only at AAS.

Register LiteLLM **at MCP**, not AAS: `POST https://YOUR_MCP/register` with `redirect_uris=["https://YOUR_LITELLM/callback"]`, `token_endpoint_auth_method="none"`, `grant_types=["authorization_code","refresh_token"]`, `response_types=["code"]`. Use the returned downstream `client_id`. Configure the exact redirect in `OUTLOOK_CLIENT_REDIRECT_URIS` first.

LiteLLM: HTTP URL `https://YOUR_MCP/mcp`, `auth_type=oauth2`, `oauth2_flow=authorization_code`, downstream client ID, endpoints `https://YOUR_MCP/authorize` and `https://YOUR_MCP/token`, requested scopes. Do not give LiteLLM the AAS client ID/secret. Discovery issuer is MCP; the AAS issuer stays in MCP configuration. The lab uses explicit browser/Docker endpoints with no LiteLLM issuer override.

Use a distinct LiteLLM `user_id` and authorized virtual key for each user. LiteLLM stores MCP-issued tokens; encrypted AAS access/refresh tokens stay in MCP. Persist both the signing key and OAuth state directory; loss of either requires downstream client re-registration and sign-in again. Signing-key rotation also changes the storage encryption key. Treat backups as secrets.

This changes MCP's OAuth role, not EWS transport: the adapter still uses scoped service-account impersonation. AAS password retrieval and user-token Exchange authentication are not implemented; those require the platform's actual contract.

## MCP settings and files

| Environment variable | Example |
|---|---|
| OUTLOOK_AUTH_MODE | `proxy` (default); `resource` retains the legacy verifier-only mode |
| OUTLOOK_AUTHORIZATION_ENDPOINT | `https://aas.corp.example/authorize` |
| OUTLOOK_TOKEN_ENDPOINT | `https://aas.corp.example/token` |
| OUTLOOK_OAUTH_CLIENT_ID | `outlook-mcp` — registered at AAS |
| OUTLOOK_OAUTH_CLIENT_SECRET_FILE | `/run/oauth-secrets/aas-client-secret` |
| OUTLOOK_OAUTH_SIGNING_KEY_FILE | `/run/oauth-secrets/oauth-signing-key` — stable random secret, >=32 characters |
| OUTLOOK_OAUTH_STORAGE_DIR | `/var/lib/outlook-mcp/oauth` — persistent, writable by UID 10001 |
| OUTLOOK_CLIENT_REDIRECT_URIS | `["https://YOUR_LITELLM/callback"]` — JSON list, exact URLs |
| OUTLOOK_TOKEN_ENDPOINT_AUTH_METHOD | `client_secret_basic` (default) or `client_secret_post` |
| OUTLOOK_BACKEND | `ews` (`demo` is synthetic only) |
| OUTLOOK_ISSUER | `https://sso.corp.example/realms/corp` |
| OUTLOOK_JWKS_URI | `https://sso.corp.example/realms/corp/protocol/openid-connect/certs` |
| OUTLOOK_AUDIENCE | `outlook-mcp` |
| OUTLOOK_PUBLIC_URL | `https://mail-mcp.corp.example` — origin **without** `/mcp` |
| OUTLOOK_EWS_ENDPOINT | `https://exchange.corp.example/EWS/Exchange.asmx` |
| OUTLOOK_EWS_USERNAME | `CORP\svc-outlook-mcp` |
| OUTLOOK_EWS_PASSWORD_FILE | `/run/secrets/ews-password` |
| OUTLOOK_MAPPING_FILE | `/run/config/mailboxes.json` |
| REQUESTS_CA_BUNDLE / SSL_CERT_FILE | `/run/ca/ca.pem` |

Mount the password separately and supply a CA bundle trusted for both Exchange and Keycloak. Do not disable certificate verification. The server listens on container port **8766**.

`mailboxes.json` is administrator-owned and uses actual Keycloak subject UUIDs:

```json
{
  "KEYCLOAK_SUBJECT_A": "mcp-test-a@corp.example",
  "KEYCLOAK_SUBJECT_B": "mcp-test-b@corp.example"
}
```

## Kubernetes / containers

Use `deploy/k8s/mcp.yaml`. Replace example DNS names and image, then provision namespace `outlook-mcp` with:

- Secret `outlook-ews`: keys `username`, `ews-password`.
- Secret `outlook-oauth`: keys `aas-client-secret`, `oauth-signing-key`.
- PVC `outlook-oauth-state`, writable by UID 10001.
- ConfigMap `outlook-mailbox-mapping`: key `mailboxes.json`.
- ConfigMap `outlook-ca`: key `ca.pem`.
- Registry pull credentials and an internal TLS ingress for MCP and its OAuth paths as required by your platform.

The manifest uses one replica, Recreate strategy and a PVC. HTTP MCP is stateless, but OAuth proxy state is persistent. Do not scale this file store across replicas: that requires shared network storage and concurrent-refresh validation. Demo mail remains in memory. Kubernetes deployment has not been tested.

`compose.internal.yaml` is an alternative for an existing Docker-based internal LiteLLM. Fill `deploy/internal.env.example`, mount the files under `.local/internal`, and use a separate Compose project. It does not provision Exchange or Keycloak.

## Tools and scopes

| Scope | Tools |
|---|---|
| Valid mapped user, no operation scope | whoami |
| outlook.read | list_folders, search_emails, get_email, get_attachment |
| outlook.write | save_draft, mark_email_read, move_email |
| outlook.send | send_draft, additionally requires confirm=true |
| contacts.read | search_contacts |
| calendar.read | list_events |
| calendar.write | save_event |

Limits: list results ≤100, message bodies ≤50,000 characters, EWS file attachments ≤5 MiB. Calendar writes create personal events without invitations. Use `move_email` to trash for recoverable deletion. `confirm=true` does not replace actual user authorization.

## Live acceptance and updates

1. OAuth sign-in → `whoami`: correct mailbox and backend=ews. This does not call Exchange.
2. `list_folders` → `search_emails` → `get_email` on a prepared real test message.
3. Download its attachment and verify bytes/hash; resolve a directory recipient; read a prepared calendar interval.
4. Save/read a real draft; change/restore read status; move/restore a test message (EWS IDs may change); create a personal event and verify it in OWA.
5. After explicit authorization, send only between test mailboxes; verify Sent Items **and recipient delivery**. Do not blindly retry an ambiguous timeout.
6. Prove user B cannot access A's items, narrow scopes deny writes/sending, expired tokens fail/refresh, and Exchange denies impersonation outside the allowed scope.

Check MCP `isError`, not just HTTP 200. `/healthz` reports process health with `exchange_verified=false`; it is not evidence of a working mailbox. Real EWS response shapes can differ from demo fixtures.

After changing mapping/secrets/config, restart the Deployment. To roll back, stop only this MCP, remove its LiteLLM access, revoke its OAuth sessions and remove only the Exchange role/scope created for this trial. The synthetic acceptance scripts must not be used to send real mail.
