# MCP Outlook with OAuth2

[Русский](README.ru.md) · [Deployment](docs/en/deployment.md) · [Architecture and origins](docs/en/architecture.md) · [Testing](docs/en/testing.md)

A self-hosted MCP server for on-premises Microsoft Exchange: user OAuth2 authentication, EWS mailbox access, and integration with LiteLLM. Outlook desktop and Microsoft Graph are not required.

**Status:** all 12 tools passed 59 synthetic-backend calls through an existing LiteLLM 1.96.0 and real Keycloak OAuth2. The local suite has 26 tests. **Live Exchange 2019 CU15 interoperability and Kubernetes deployment have not yet been verified.**

```text
User → LiteLLM → MCP → Exchange EWS
          ↕      ↓
       Keycloak  JWT + scopes + subject-to-mailbox mapping
```

MCP accepts Keycloak access tokens via Authorization Code + PKCE. The EWS adapter separately uses HTTPS + NTLM with a scoped impersonation service account. OAuth2 at MCP does not turn Exchange authentication into OAuth2.

## Capabilities

Mail search/read, attachment download, saved drafts and confirmed sending, read flags, message moves, directory lookup, and personal calendar events. See the [tool/scope table](docs/en/deployment.md#tools-and-scopes).

This is an independent implementation using **FastMCP** and **exchangelib**. **It is not a fork of ItayElizur/mcp-outlook and copies none of its code.** The inspected reference commit, differences, and reasons are documented [here](docs/en/architecture.md).

## Get the code and build

```sh
git clone https://github.com/iasemin/mcp-outlook-with-oauth.git
cd mcp-outlook-with-oauth
uv sync --frozen
uv run pytest -q

docker buildx build --platform linux/amd64 \
  -t YOUR_REGISTRY/mcp-outlook-with-oauth:0.1.0 --push .
```

No container image is published by this repository yet; build and push to your own registry. Python package/module names remain `outlook-ews-mcp` / `outlook_mcp`.

## Deployment

- **Internal Exchange / Kubernetes:** [short deployment guide](docs/en/deployment.md); manifests in `deploy/k8s/mcp.yaml`.
- **Local OAuth stand:** [reproduction steps](docs/en/testing.md); Compose starts Keycloak, PostgreSQL, MCP and an ingress to an **existing** LiteLLM. It does not install LiteLLM or Exchange.
- **Evidence:** [59-call synthetic test report](docs/all-tools-results.json). No real mailbox data or credentials are included.

MIT license for this project's code. Dependencies retain their own licenses. This project is not affiliated with Microsoft.
