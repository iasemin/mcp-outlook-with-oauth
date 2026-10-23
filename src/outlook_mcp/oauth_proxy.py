"""Apply exact deployment redirect policy on top of FastMCP's pattern allowlist."""

from fastmcp.server.auth import OAuthProxy
from mcp.server.auth.provider import AuthorizeError, RegistrationError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl


class StrictOAuthProxy(OAuthProxy):
    def _allowed_exactly(self, uri) -> bool:
        return str(uri) in {str(AnyUrl(value)) for value in self._allowed_client_redirect_uris or []}

    async def register_client(self, client_info):
        if not client_info.redirect_uris or not all(
            self._allowed_exactly(uri) for uri in client_info.redirect_uris
        ):
            raise RegistrationError("invalid_redirect_uri", "Redirect URI is not explicitly allowed")
        await super().register_client(client_info)

    async def get_client(self, client_id):
        # FastMCP otherwise synthesizes an unregistered downstream client for this ID.
        if client_id == self._upstream_client_id:
            return None
        client = await super().get_client(client_id)
        if client is None or not all(self._allowed_exactly(uri) for uri in client.redirect_uris or []):
            return None
        # The SDK validates redirect URIs before invoking authorize(), including
        # error redirects. Return its exact-match model, not FastMCP's pattern model.
        return OAuthClientInformationFull.model_validate(client.model_dump())

    async def authorize(self, client, params):
        registered = {str(uri) for uri in client.redirect_uris or []}
        if not self._allowed_exactly(params.redirect_uri) or str(params.redirect_uri) not in registered:
            raise AuthorizeError("invalid_request", "Redirect URI does not exactly match registration")
        return await super().authorize(client, params)
