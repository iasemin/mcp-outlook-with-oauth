import pytest

from outlook_mcp.identity import IdentityError, principal_from_claims

MAPPING = {"alice-id": "alice@lab.example", "bob-id": "bob@lab.example"}


def test_subject_mapping_overrides_email_claim():
    user = principal_from_claims(
        {"sub": "alice-id", "email": "bob@lab.example", "scope": "outlook.read"},
        MAPPING,
        ["outlook.read"],
    )
    assert user.mailbox == "alice@lab.example"


@pytest.mark.parametrize("claims", [{}, {"sub": "unknown"}, {"sub": "alice-id", "scope": "calendar.read"}])
def test_missing_subject_or_scope_is_denied(claims):
    with pytest.raises(IdentityError):
        principal_from_claims(claims, MAPPING, ["outlook.read"])


def test_unmapped_user_cannot_choose_mailbox():
    with pytest.raises(IdentityError):
        principal_from_claims(
            {"sub": "unknown", "email": "alice@lab.example", "scope": "outlook.read"}, MAPPING, []
        )


def test_id_token_is_not_access_token():
    with pytest.raises(IdentityError):
        principal_from_claims({"sub": "alice-id", "typ": "ID", "scope": "outlook.read"}, MAPPING, [])
