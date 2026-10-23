# Basis, changes and reasons

[Русский](../ru/architecture.md)

## MCP as the AAS OAuth2 client

Previously MCP only verified Keycloak tokens while LiteLLM was the upstream OAuth client. The revised requirement moves that role to **FastMCP OAuthProxy**: MCP is the confidential AAS client, receives `/auth/callback`, exchanges codes with S256 PKCE and refreshes upstream tokens. MCP is a separate authorization server for LiteLLM and issues its own tokens. The AAS secret no longer goes to LiteLLM; the old direct client is disabled in the lab.

We use the existing OAuthProxy rather than implementing the protocol ourselves: consent/CSRF, state, PKCE, downstream registration and token binding remain in the library. Our configuration restricts redirect URIs, verifies upstream JWTs and persists OAuth state with FileTreeStore + Fernet. A stable key, persistent volume and one replica are required. Legacy verification-only mode is explicit: `OUTLOOK_AUTH_MODE=resource`.

This does not extract passwords from OAuth2 or prove Exchange user-token authentication. The EWS adapter still uses a service account. Actual AAS integration depends on its contract.

## What we actually used

- **[FastMCP](https://github.com/PrefectHQ/fastmcp):** tool registration, HTTP MCP, JWT/JWKS verification and protected-resource discovery. The tested lock contains 3.4.11.
- **[exchangelib](https://github.com/ecederstrand/exchangelib):** EWS data types, mailbox operations and NTLM transport. The tested lock contains 5.6.0. We did not implement EWS/SOAP from scratch.
- **Keycloak + PostgreSQL:** real user OAuth2 in the local stand. **Existing LiteLLM 1.96.0:** gateway and per-user token storage/refresh.

The application code in `src/outlook_mcp`, tests and deployment files were written independently. The project is not derived from the reference repository below. Library use and architectural inspiration are different from copying source.

## Reference that we inspected

[ItayElizur/mcp-outlook, commit 9faaedf](https://github.com/ItayElizur/mcp-outlook/tree/9faaedf7e1aab586bd24058a80055b777cb1efda) was evaluated as a possible starting point. We retained the **concept** of verifying the user at MCP and separately using EWS impersonation. We chose independent implementation rather than a fork.

These observations apply to that commit, not necessarily later versions. No LICENSE file or pyproject license declaration was found at the inspected commit. This was one reason not to copy or redistribute its source.

| Reference / decision point | Our implementation | Why |
|---|---|---|
| Static mode is unauthenticated; JWT mode is optional | Authentication required on every MCP method | Remote internal gateway must not expose unauthenticated tools |
| Verifier receives issuer, audience and keys | FastMCP verifier plus mandatory `exp`, access-token type, `sub`, and `nbf`/`iat` checks | Reject non-expiring, future and ID tokens; keep signature cryptography in the library |
| Mailbox selected from configurable email claim | Exact issuer + administrator-owned `sub → SMTP` mapping | Editable email/profile claims cannot redirect access |
| No per-operation scope enforcement in the inspected tools | Six operation scopes, checked before backend calls | Separate reading, writing and sending |
| Sending and event creation are app-only MCP Apps tools | Plain MCP tools with structured results | LiteLLM clients need no compose widget |
| Draft workflows return UI data | `save_draft` persists an unsent backend item | A displayed draft must not be confused with an Exchange draft |
| Exceptions may become normal error dictionaries | MCP `isError`; generic backend faults masked | Gateway/tests can distinguish failures without exposing internal exception text |
| Permanent deletion can be requested | Recoverable move to trash; no permanent-delete tool | Keep first-version writes reversible where possible |
| Reference defaults EWS schema to Exchange2013 | Library negotiates supported EWS version | Avoid an arbitrary default; schema name alone never proves 2019 incompatibility |
| No container/Kubernetes manifests in inspected tree | Non-root image, read-only filesystem, external secrets/config, stateless HTTP | Run in containers; OAuth proxy mode currently uses one replica with persistent state |
| Mocked token-routing tests | API tests + live Keycloak → existing LiteLLM → MCP acceptance | Test OAuth, per-user routing and refresh across real components |

`confirm=true` is an API precondition, **not an independent human approval mechanism**. A client must obtain actual user authorization before sending. An ambiguous EWS send timeout must not trigger blind application retries.

## Deliberate limits

12 tools are implemented, not the entire Outlook feature set. Thread-preserving reply/forward, draft editing, attachment upload, categories, free/busy, meeting invitations/responses and shared-mailbox delegation remain extensions.

The demo backend is a small in-memory synthetic store, not an Exchange emulator. Its search, contacts and calendar behavior do not prove EWS behavior. Live CU15 interoperability, Exchange delivery, NTLM/Extended Protection and Kubernetes operation remain unverified. Public source and a passing synthetic suite are not a production-readiness claim.
