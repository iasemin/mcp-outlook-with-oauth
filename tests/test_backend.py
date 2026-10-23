import pytest

from outlook_mcp.demo import DemoBackend


def test_mailbox_item_ids_cannot_cross_accounts():
    backend = DemoBackend()
    item = backend.list_mail("alice@lab.example", "inbox", 10, "")[0]
    with pytest.raises(LookupError):
        backend.get_mail("bob@lab.example", item["id"], "inbox")


def test_draft_can_only_be_sent_by_its_owner():
    backend = DemoBackend()
    draft = backend.save_draft("alice@lab.example", ["bob@lab.example"], "Test", "Body", [], [])
    with pytest.raises(LookupError):
        backend.send_draft("bob@lab.example", draft["id"])
    assert backend.send_draft("alice@lab.example", draft["id"])["status"] == "sent"
    with pytest.raises(LookupError):
        backend.send_draft("alice@lab.example", draft["id"])


def test_listing_marks_synthetic_data():
    backend = DemoBackend()
    assert backend.list_mail("alice@lab.example", "inbox", 1, "")[0]["synthetic"] is True


def test_synthetic_attachment_can_be_downloaded_and_is_owned():
    import base64

    backend = DemoBackend()
    item = backend.list_mail("alice@lab.example", "inbox", 10, "")[0]
    attachment = backend.get_attachment("alice@lab.example", item["id"], "inbox", "stand-note.txt")
    assert base64.b64decode(attachment["content_base64"]) == b"Synthetic attachment for alice@lab.example\n"
    assert item["attachments"] == [{"name": "stand-note.txt", "size": 43}]
    with pytest.raises(LookupError):
        backend.get_attachment("bob@lab.example", item["id"], "inbox", "stand-note.txt")
    with pytest.raises(LookupError):
        backend.get_attachment("alice@lab.example", item["id"], "inbox", "missing.txt")


def test_synthetic_contacts_filter_query():
    backend = DemoBackend()
    assert backend.search_contacts("alice@lab.example", "stand", 10)
    assert backend.search_contacts("alice@lab.example", "no-such-contact", 10) == []
