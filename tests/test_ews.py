from pathlib import Path
from unittest.mock import Mock

import pytest

from outlook_mcp.config import Settings
from outlook_mcp.ews import EwsBackend


def config(tmp_path):
    mapping = tmp_path / "map.json"
    mapping.write_text('{"user": "alice@lab.example"}')
    return Settings(
        backend="ews",
        issuer="https://idp.example/realms/corp",
        jwks_uri="https://idp.example/keys",
        mapping_file=Path(mapping),
        ews_endpoint="https://exchange.example/EWS/Exchange.asmx",
        ews_username="LAB\\svc-mcp",
        ews_password="test-only",
    )


def test_ews_routes_only_to_authenticated_account(tmp_path, monkeypatch):
    import outlook_mcp.ews as module

    factory = Mock()
    monkeypatch.setattr(module, "Account", factory)
    backend = EwsBackend(config(tmp_path))
    backend.account("alice@lab.example")
    assert factory.call_args.kwargs["primary_smtp_address"] == "alice@lab.example"
    assert factory.call_args.kwargs["autodiscover"] is False
    assert factory.call_args.kwargs["access_type"] == module.IMPERSONATION


def test_message_lookup_checks_parent_folder(tmp_path):
    backend = EwsBackend(config(tmp_path))
    account = Mock()
    account.inbox.id = "alice-inbox"
    message = Mock()
    message.parent_folder_id.id = "bob-inbox"
    account.inbox.get.return_value = message
    with pytest.raises(LookupError):
        backend._message(account, "foreign-id", "inbox")


def test_ews_does_not_accept_plain_http_endpoint(tmp_path):
    with pytest.raises(ValueError):
        Settings(
            backend="ews",
            issuer="https://issuer.example",
            jwks_uri="https://issuer.example/keys",
            mapping_file=tmp_path / "map.json",
            ews_endpoint="http://exchange/EWS/Exchange.asmx",
        )


def test_ews_text_search_uses_querystring_not_nonexistent_field(tmp_path, monkeypatch):
    from exchangelib import Q

    backend = EwsBackend(config(tmp_path))
    account = Mock()
    items = Mock()
    queries = []
    account.inbox.all.return_value = items

    def apply_filter(*args, **kwargs):
        queries.append(Q(*args, **kwargs))
        return items

    items.filter.side_effect = apply_filter
    items.only.return_value = items
    # QuerySet slicing supplies the actual iterable consumed by the adapter.
    from unittest.mock import MagicMock

    items.order_by.return_value = MagicMock()
    items.order_by.return_value.__getitem__.return_value = []
    monkeypatch.setattr(backend, "account", lambda mailbox: account)
    backend.list_mail("alice@lab.example", "inbox", 20, "subject:stand")
    assert queries[0].query_string == "subject:stand"
