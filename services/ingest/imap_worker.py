"""IMAP polling worker for converting alert emails into events."""
from __future__ import annotations

import email
import imaplib
import time
from typing import Dict, Iterable, List

import structlog

from services.common.models import Event, RawEventMetadata
from services.ingest.email_parser import EmailParser

logger = structlog.get_logger(__name__)


class IMAPPoller:
    def __init__(self, config: Dict[str, str], parser: EmailParser):
        self.config = config
        self.parser = parser

    def run_once(self) -> List[Event]:
        logger.info("imap.poll.start", host=self.config.get("imap_host"))
        with imaplib.IMAP4_SSL(self.config["imap_host"], int(self.config.get("imap_port", 993))) as client:
            client.login(self.config["username"], self.config["password"])
            client.select(self.config.get("folder", "INBOX"))
            typ, data = client.search(None, self.config.get("search_filter", "ALL"))
            events: List[Event] = []
            for num in data[0].split():
                typ, msg_data = client.fetch(num, "(RFC822)")
                if typ != "OK":
                    logger.warning("imap.fetch.failed", status=typ)
                    continue
                message = email.message_from_bytes(msg_data[0][1])
                events.extend(self._handle_message(message))
                client.store(num, "+FLAGS", "(\\Seen)")
            logger.info("imap.poll.done", events=len(events))
            return events

    def poll_forever(self, callback) -> None:  # pragma: no cover - long running
        interval = int(self.config.get("interval_seconds", 60))
        while True:
            try:
                events = self.run_once()
                for event in events:
                    callback(event)
            except Exception as exc:  # noqa: BLE001
                logger.exception("imap.poll.error", error=str(exc))
            time.sleep(interval)

    def _handle_message(self, message) -> Iterable[Event]:
        metadata = RawEventMetadata(
            mail_subject=message.get("Subject"),
            mail_id=message.get("Message-Id"),
            source="imap",
            payload={"subject": message.get("Subject")},
        )
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                body = part.get_payload(decode=True).decode(errors="ignore")
                yield from self.parser.parse(body, metadata)
                return
            if content_type == "application/json":
                payload = part.get_payload(decode=True).decode(errors="ignore")
                yield from self.parser.parse_json_attachment(payload, metadata)
                return
        if message.get_content_type() == "text/plain":
            body = message.get_payload(decode=True).decode(errors="ignore")
            yield from self.parser.parse(body, metadata)
