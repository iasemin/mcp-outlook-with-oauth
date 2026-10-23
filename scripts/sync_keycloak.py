"""Apply the lab client's declarative settings to an already imported local realm."""

import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    from init_lab import main as initialize

    initialize()
    creds = json.loads((ROOT / ".local/credentials.json").read_text())
    realm = json.loads((ROOT / ".local/keycloak-realm.json").read_text())
    with httpx.Client(base_url="http://localhost:8800", timeout=30) as client:
        response = client.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": "lab-admin",
                "password": creds["admin"],
            },
        )
        assert response.status_code == 200, "Local Keycloak admin authentication failed"
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        response = client.put(
            "/admin/realms/outlook-lab", json={"accessTokenLifespan": realm["accessTokenLifespan"]}
        )
        assert response.status_code == 204, "Realm token lifetime update failed"
        response = client.get("/admin/realms/outlook-lab/clients", params={"clientId": "outlook-mcp"})
        assert response.status_code == 200
        if not response.json():
            created = client.post("/admin/realms/outlook-lab/clients", json=realm["clients"][0])
            assert created.status_code == 201, "MCP client creation failed"
            response = client.get("/admin/realms/outlook-lab/clients", params={"clientId": "outlook-mcp"})
        assert len(response.json()) == 1
        current = response.json()[0]
        response = client.put(
            "/admin/realms/outlook-lab/clients/" + current["id"], json=current | realm["clients"][0]
        )
        assert response.status_code == 204, "Keycloak client update failed"
        # Keycloak client PUT does not remove existing default scope bindings.
        # Manage those subresources explicitly so a narrow OAuth request stays narrow.
        client_path = "/admin/realms/outlook-lab/clients/" + current["id"]
        configured = realm["clients"][0]
        for kind, desired_names in [
            ("default", configured["defaultClientScopes"]),
            ("optional", configured["optionalClientScopes"]),
        ]:
            path = client_path + "/" + kind + "-client-scopes"
            existing = client.get(path)
            assert existing.status_code == 200
            for bound in existing.json():
                if bound["name"] not in desired_names:
                    assert client.delete(path + "/" + bound["id"]).status_code == 204
            scopes = client.get("/admin/realms/outlook-lab/client-scopes")
            assert scopes.status_code == 200
            for scope in scopes.json():
                if scope["name"] in desired_names:
                    assert client.put(path + "/" + scope["id"]).status_code == 204
        legacy = client.get("/admin/realms/outlook-lab/clients", params={"clientId": "outlook-litellm"})
        assert legacy.status_code == 200
        for old in legacy.json():
            assert (
                client.put(
                    "/admin/realms/outlook-lab/clients/" + old["id"], json=old | {"enabled": False}
                ).status_code
                == 204
            )
    print(
        "MCP upstream client synchronized; legacy direct LiteLLM client disabled; password grant remains disabled for mail users."
    )


if __name__ == "__main__":
    main()
