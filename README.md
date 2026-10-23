# MCP Outlook with OAuth2

[Русский](README.ru.md) · [Deployment](docs/en/deployment.md) · [Architecture and origins](docs/en/architecture.md) · [Testing](docs/en/testing.md)

A self-hosted MCP server for on-premises Microsoft Exchange: user OAuth2 authentication, EWS mailbox access, and integration with LiteLLM. Outlook desktop and Microsoft Graph are not required.

**Status:** all 12 tools passed 59 synthetic-backend calls through an existing LiteLLM 1.96.0 and real Keycloak OAuth2. The local suite has 32 tests. **Live Exchange 2019 CU15 interoperability and Kubernetes deployment have not yet been verified.**

```text
LiteLLM → MCP OAuth proxy → Exchange EWS
              ↕
       AAS / Keycloak (lab)
```

**MCP is the confidential OAuth2 client of AAS.** It receives the callback, exchanges codes with PKCE, refreshes AAS tokens and stores them encrypted. LiteLLM receives separate MCP tokens; the AAS client secret stays in MCP. Keycloak substitutes for AAS in the lab. Exchange access still uses separate HTTPS + NTLM service-account impersonation. AAS password retrieval is not implemented; the actual platform contract is still required.

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
  -t YOUR_REGISTRY/mcp-outlook-with-oauth:0.2.0 --push .
```

No container image is published by this repository yet; build and push to your own registry. Python package/module names remain `outlook-ews-mcp` / `outlook_mcp`.

## Deployment

- **Internal Exchange / Kubernetes:** [short deployment guide](docs/en/deployment.md); manifests in `deploy/k8s/mcp.yaml`.
- **Local OAuth stand:** [reproduction steps](docs/en/testing.md); Compose starts Keycloak, PostgreSQL, MCP and an ingress to an **existing** LiteLLM. It does not install LiteLLM or Exchange.
- **Evidence:** [59-call synthetic test report](docs/all-tools-results.json). No real mailbox data or credentials are included.

MIT license for this project's code. Dependencies retain their own licenses. This project is not affiliated with Microsoft.
