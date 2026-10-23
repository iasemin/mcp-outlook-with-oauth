"""Signature validation stays in FastMCP; enforce mandatory access-token semantics here."""

import time

from fastmcp.server.auth.providers.jwt import JWTVerifier


class AccessTokenVerifier(JWTVerifier):
    async def verify_token(self, token: str):
        if len(token) > 16384:
            return None
        validated = await super().verify_token(token)
        if validated is None:
            return None
        claims = validated.claims
        now = time.time()
        if claims.get("typ") != "Bearer" or not isinstance(claims.get("sub"), str):
            return None
        exp = claims.get("exp")
        if type(exp) not in (int, float) or not now < exp:
            return None
        for name in ("nbf", "iat"):
            value = claims.get(name)
            if value is not None and (type(value) not in (int, float) or value > now + 5):
                return None
        return validated
