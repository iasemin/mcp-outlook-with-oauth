from collections.abc import Mapping
from dataclasses import dataclass


class IdentityError(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    mailbox: str
    scopes: frozenset[str]


def principal_from_claims(claims: dict, mapping: Mapping[str, str], required: list[str]) -> Principal:
    subject = claims.get("sub")
    if claims.get("typ", "Bearer") != "Bearer":
        raise IdentityError("An access token is required")
    if not isinstance(subject, str) or subject not in mapping:
        raise IdentityError("Subject has no provisioned mailbox")
    scopes = frozenset(str(claims.get("scope", "")).split())
    if not set(required).issubset(scopes):
        raise IdentityError("Required operation scope is missing")
    return Principal(subject, mapping[subject], scopes)
