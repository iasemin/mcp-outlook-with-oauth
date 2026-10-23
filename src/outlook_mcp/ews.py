"""Real EWS backend. Integration against Exchange 2019 CU15 remains a separate acceptance gate."""

import base64
from datetime import datetime

from exchangelib import (
    IMPERSONATION,
    NTLM,
    Account,
    CalendarItem,
    Configuration,
    Credentials,
    EWSDateTime,
    FaultTolerance,
    FileAttachment,
    Mailbox,
    Message,
)
from exchangelib.errors import ErrorItemNotFound

from .config import Settings


class EwsBackend:
    name = "ews"

    def __init__(self, settings: Settings):
        self.settings = settings

    def account(self, mailbox):
        # HTTPS verification stays enabled. Install internal CA through REQUESTS_CA_BUNDLE.
        config = Configuration(
            service_endpoint=self.settings.ews_endpoint,
            credentials=Credentials(self.settings.ews_username, self.settings.password()),
            auth_type=NTLM,
            max_connections=2,
            retry_policy=FaultTolerance(max_wait=15),
        )
        return Account(
            primary_smtp_address=mailbox, config=config, access_type=IMPERSONATION, autodiscover=False
        )

    def _folder(self, account, folder):
        names = {"inbox": "inbox", "sent": "sent", "drafts": "drafts", "trash": "trash", "junk": "junk"}
        if folder in names:
            return getattr(account, names[folder])
        for item in account.msg_folder_root.walk():
            if item.id == folder:
                return item
        raise LookupError("Folder not found in this mailbox")

    def _message(self, account, item_id, folder):
        parent = self._folder(account, folder)
        try:
            message = parent.get(id=item_id)
        except ErrorItemNotFound:
            raise LookupError("Item not found in this mailbox/folder") from None
        # GetItem can resolve an opaque ID outside the requested folder: verify ownership.
        if not message.parent_folder_id or message.parent_folder_id.id != parent.id:
            raise LookupError("Item not found in this mailbox/folder")
        return message

    @staticmethod
    def _mail(message, folder, detail=False):
        result = {
            "id": message.id,
            "folder": folder,
            "subject": message.subject,
            "sender": getattr(message.sender, "email_address", None),
            "received": str(message.datetime_received) if message.datetime_received else None,
            "is_read": message.is_read,
            "synthetic": False,
        }
        if detail:
            result.update(
                body=str(message.body or "")[:50000],
                to=[r.email_address for r in message.to_recipients or []],
                cc=[r.email_address for r in message.cc_recipients or []],
                attachments=[{"name": a.name, "size": a.size} for a in message.attachments or []],
            )
        return result

    def list_folders(self, mailbox):
        account = self.account(mailbox)
        return [{"id": folder.id, "name": folder.name} for folder in account.msg_folder_root.walk()][:100]

    def list_mail(self, mailbox, folder, limit, query):
        account = self.account(mailbox)
        items = self._folder(account, folder).all()
        if query:
            items = items.filter(query)
        items = items.only("subject", "sender", "datetime_received", "is_read").order_by("-datetime_received")
        return [self._mail(item, folder) for item in items[:limit]]

    def get_mail(self, mailbox, item_id, folder):
        return self._mail(self._message(self.account(mailbox), item_id, folder), folder, detail=True)

    def get_attachment(self, mailbox, item_id, folder, name):
        msg = self._message(self.account(mailbox), item_id, folder)
        for attachment in msg.attachments or []:
            if attachment.name == name and isinstance(attachment, FileAttachment):
                if attachment.size is None or attachment.size > 5 * 1024 * 1024:
                    raise ValueError("Attachment exceeds 5 MiB or has unknown size")
                data = attachment.content
                if len(data) > 5 * 1024 * 1024:
                    raise ValueError("Attachment exceeds 5 MiB")
                return {"name": name, "content_base64": base64.b64encode(data).decode(), "synthetic": False}
        raise LookupError("File attachment not found")

    def save_draft(self, mailbox, to, subject, body, cc, bcc):
        account = self.account(mailbox)
        message = Message(
            account=account,
            folder=account.drafts,
            subject=subject,
            body=body,
            to_recipients=[Mailbox(email_address=x) for x in to],
            cc_recipients=[Mailbox(email_address=x) for x in cc],
            bcc_recipients=[Mailbox(email_address=x) for x in bcc],
        )
        message.save()
        return {"id": message.id, "status": "draft", "synthetic": False}

    def send_draft(self, mailbox, item_id):
        message = self._message(self.account(mailbox), item_id, "drafts")
        if not message.is_draft:
            raise ValueError("Item is not an unsent draft")
        # No application retry on ambiguous delivery; caller must inspect Sent Items.
        message.send_and_save()
        return {"status": "sent", "synthetic": False}

    def update_mail(self, mailbox, item_id, folder, is_read):
        message = self._message(self.account(mailbox), item_id, folder)
        message.is_read = is_read
        message.save(update_fields=["is_read"])
        return {"status": "updated", "synthetic": False}

    def move_mail(self, mailbox, item_id, folder, destination):
        if destination == "drafts":
            raise ValueError("Existing mail cannot be converted to a draft")
        account = self.account(mailbox)
        target = self._folder(account, destination)
        if target.id == account.drafts.id:
            raise ValueError("Existing mail cannot be converted to a draft")
        message = self._message(account, item_id, folder)
        message.move(to_folder=target)
        return {"status": "moved", "id": message.id, "synthetic": False}

    def search_contacts(self, mailbox, query, limit):
        account = self.account(mailbox)
        people = account.protocol.resolve_names(names=[query], return_full_contact_data=False)
        return [{"name": item.name, "email": item.email_address} for item in people][:limit]

    def list_events(self, mailbox, start, end, limit):
        account = self.account(mailbox)
        a, b = (
            EWSDateTime.from_datetime(datetime.fromisoformat(start)),
            EWSDateTime.from_datetime(datetime.fromisoformat(end)),
        )
        return [
            {
                "id": item.id,
                "subject": item.subject,
                "start": str(item.start),
                "end": str(item.end),
                "location": item.location,
                "synthetic": False,
            }
            for item in account.calendar.view(start=a, end=b).order_by("start")[:limit]
        ]

    def save_event(self, mailbox, subject, start, end, location):
        account = self.account(mailbox)
        item = CalendarItem(
            account=account,
            folder=account.calendar,
            subject=subject,
            location=location,
            start=EWSDateTime.from_datetime(datetime.fromisoformat(start)),
            end=EWSDateTime.from_datetime(datetime.fromisoformat(end)),
        )
        item.save(send_meeting_invitations="SendToNone")
        return {"id": item.id, "status": "saved", "synthetic": False}
