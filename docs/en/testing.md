# Local testing and evidence

[Русский](../ru/testing.md)

## Reproduce the stand

Requires Docker, Python ≥3.12, uv, and an **existing Docker-based LiteLLM** with a database and management API. Tested gateway version: 1.96.0. This repository does not deploy LiteLLM.

```sh
uv sync --frozen
uv run python scripts/init_lab.py
# If necessary, edit LITELLM_NETWORK in generated .env and the upstream
# LiteLLM container name in deploy/nginx/default.conf.
docker compose up -d --build
# Wait until Keycloak and MCP are healthy.
uv run python scripts/sync_keycloak.py
uv run python scripts/litellm_admin.py
uv run python scripts/acceptance.py
uv run python scripts/all_tools_acceptance.py
```

Defaults match the recorded test environment: Docker network `litellm_guardrails_default`, LiteLLM container `litellm_guardrails-litellm-1`. For another container, set `LITELLM_CONTAINER` when running the Python scripts and update nginx upstream. `init_lab.py` rewrites `.env`; apply network overrides after it. `LITELLM_URL` overrides the scripts' default `http://localhost:8400`.

`litellm_admin.py` reads the existing proxy's configured admin key through Docker exec **in memory**, then registers `outlook_lab` using its management API. Use it only as that gateway's authorized administrator. Dedicated user keys are restricted to this MCP. No upstream model is called.

Local addresses: LiteLLM ingress `:8400`, Keycloak `:8800`, MCP `:8766/mcp`, process health `:8766/healthz`. Newly exposed ports bind to localhost. The ingress keeps the server internal without changing gateway-wide IP rules. Keycloak start-dev, HTTP localhost and generated users are lab-only.

Generated credentials and tokens live only in ignored `.local/` and `.env`. The local directory is host-private; readable realm/mapping bind files let container UIDs access them. Do not commit these files. Secrets are reused, not rotated; sync applies scope bindings to an already imported realm. The mail client disables password grants; the setup script uses the generated local bootstrap admin separately.

## What was actually verified

Recorded on 2026-10-23:

- **26 API/unit tests**, including signature, issuer, audience, expiry, future claims, ID-token rejection, scopes and subject binding.
- **12/12 tools**, **59 calls through LiteLLM**: 29 success and 30 expected denial. [Machine-readable results](../all-tools-results.json).
- Real user Authorization Code + S256 PKCE, per-user gateway token persistence, a real 45-second token expiry, automatic refresh and explicit refresh.
- Owned synthetic mail/drafts, read flags, move/restore, directory filtering, personal events and downloaded attachment bytes/hash.
- Cross-user access, narrow scopes, invalid input, missing confirmations and repeat sends rejected.

```sh
uv run pytest -q
uv run ruff check src tests scripts
```

The full-tool script refuses to run when `/healthz` reports a non-demo backend. The lifecycle script also expects synthetic data. Python's test browser emulates the localhost Secure-cookie exception for generated lab users only. Never copy this cookie handling into a remote production client.

The synthetic store does not deliver mail or emulate Exchange. EWS authentication, RBAC, delivery and CU15 behavior remain unverified. Kubernetes YAML was parsed, not cluster-tested. Test helpers using mocks are not live Exchange evidence.

Stop with `docker compose stop`; `docker compose down` removes this stand but keeps its PostgreSQL volume. Neither command stops existing LiteLLM or deletes its `outlook_lab` database registration. Keep the generated credentials with the retained Keycloak database.
