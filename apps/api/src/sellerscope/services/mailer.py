"""Outbound email. SMTP in all environments (Mailpit locally, a provider's SMTP in production)."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

from sellerscope.core.config import Settings


class Mailer(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=10) as smtp:
            if self._s.smtp_starttls:
                smtp.starttls()
            if self._s.smtp_username and self._s.smtp_password:
                smtp.login(self._s.smtp_username, self._s.smtp_password.get_secret_value())
            smtp.send_message(message)

    async def send(self, message: EmailMessage) -> None:
        if "From" not in message:
            message["From"] = self._s.smtp_from
        await asyncio.to_thread(self._send_sync, message)


def build_message(to: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message
