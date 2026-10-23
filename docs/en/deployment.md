# Deployment and configuration

[Русский](../ru/deployment.md) · [Architecture](architecture.md)

## Build

```sh
git clone https://github.com/iasemin/mcp-outlook-with-oauth.git
cd mcp-outlook-with-oauth
docker buildx build --platform linux/amd64 \
  -t YOUR_REGISTRY/mcp-outlook-with-oauth:0.1.0 --push .
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

## Keycloak / LiteLLM

Create a confidential OIDC client, e.g. `outlook-litellm`:

- Standard Flow on, PKCE **S256 required**; Direct Access Grants and Service Accounts off.
- Exact callback `https://YOUR_LITELLM/callback`.
- Access token: stable `sub`, canonical `iss`, `aud` containing `outlook-mcp`, `exp`, `typ=Bearer`, and requested scopes. Add the Subject and Audience mappers to the access token.
- Define the operation scopes below as optional client scopes; authorize their issuance through your IdP policies. Optional scope registration alone does not limit which users may request it.

Register a new LiteLLM MCP entry: HTTP transport, `https://YOUR_MCP/mcp`, `auth_type=oauth2`, `oauth2_flow=authorization_code`, client ID/secret and requested scopes. Use a consistent HTTPS issuer reachable by browser, LiteLLM and MCP. In tested LiteLLM 1.96.0, a configured issuer overrides manual endpoint URLs; do not mix incompatible discovery and manual addresses.

Use separate LiteLLM `user_id` values and explicitly allowed virtual keys (`object_permission.mcp_servers`). User OAuth refresh tokens live in LiteLLM, not MCP. The OAuth client secret belongs to LiteLLM; MCP only needs JWKS.

## MCP settings and files

| Environment variable | Example |
|---|---|
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
- ConfigMap `outlook-mailbox-mapping`: key `mailboxes.json`.
- ConfigMap `outlook-ca`: key `ca.pem`.
- Registry pull credentials and an internal TLS ingress for `/mcp` as required by your platform.

The manifest provides non-root UID 10001, a read-only filesystem, resource limits, process-health probes and a Service. Start with one replica; EWS mode uses stateless HTTP and supports scaling. Demo state is in-memory and must remain single-replica. These manifests have not been deployed to a cluster yet.

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
