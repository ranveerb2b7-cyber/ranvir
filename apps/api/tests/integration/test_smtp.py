"""SmtpMailer delivers through a real SMTP server (aiosmtpd), as Mailpit would receive it."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from email import message_from_bytes
from typing import Any

import pytest
from aiosmtpd.controller import Controller

from sellerscope.core.config import AppEnv, Settings
from sellerscope.services.invitations import invitation_email
from sellerscope.services.mailer import SmtpMailer

pytestmark = pytest.mark.integration


class Sink:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:  # noqa: N802
        self.messages.append(envelope)
        return "250 OK"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def smtp() -> Iterator[tuple[Sink, int]]:
    sink, port = Sink(), _free_port()
    controller = Controller(sink, hostname="127.0.0.1", port=port)
    controller.start()
    yield sink, port
    controller.stop()


async def test_invitation_email_delivered_over_smtp(smtp: tuple[Sink, int]) -> None:
    sink, port = smtp
    settings = Settings(
        app_env=AppEnv.TEST, smtp_host="127.0.0.1", smtp_port=port, web_base_url="https://app.x"
    )
    message = invitation_email(
        settings, to="new@example.com", org_name="Acme", inviter="owner@example.com", token="tok"
    )
    await SmtpMailer(settings).send(message)

    assert len(sink.messages) == 1
    envelope = sink.messages[0]
    assert envelope.rcpt_tos == ["new@example.com"]
    parsed = message_from_bytes(envelope.content)
    assert parsed["From"] == settings.smtp_from
    assert parsed["Subject"] == "You're invited to Acme on SellerScope"
    assert "https://app.x/accept-invite?token=tok" in parsed.get_payload(decode=True).decode()
