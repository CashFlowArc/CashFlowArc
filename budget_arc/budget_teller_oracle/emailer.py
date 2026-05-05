from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from .config import load_env_file


@dataclass(frozen=True)
class EmailConfig:
    host: str | None
    port: int
    username: str | None
    password: str | None
    sender: str | None
    use_tls: bool
    use_ssl: bool
    timeout: int

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_email_config() -> EmailConfig:
    load_env_file()
    return EmailConfig(
        host=os.getenv("BUDGET_SMTP_HOST") or None,
        port=int(os.getenv("BUDGET_SMTP_PORT", "587")),
        username=os.getenv("BUDGET_SMTP_USERNAME") or None,
        password=os.getenv("BUDGET_SMTP_PASSWORD") or None,
        sender=os.getenv("BUDGET_EMAIL_FROM") or None,
        use_tls=_bool_env("BUDGET_SMTP_USE_TLS", True),
        use_ssl=_bool_env("BUDGET_SMTP_USE_SSL", False),
        timeout=int(os.getenv("BUDGET_SMTP_TIMEOUT", "20")),
    )


def send_email(*, to_email: str, subject: str, body: str) -> None:
    config = load_email_config()
    if not config.configured:
        raise RuntimeError("BudgetArc email delivery is not configured")

    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    if config.use_ssl:
        with smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=ssl.create_default_context()) as smtp:
            if config.username:
                smtp.login(config.username, config.password or "")
            smtp.send_message(message)
        return

    with smtplib.SMTP(config.host, config.port, timeout=config.timeout) as smtp:
        if config.use_tls:
            smtp.starttls(context=ssl.create_default_context())
        if config.username:
            smtp.login(config.username, config.password or "")
        smtp.send_message(message)


def send_verification_email(*, to_email: str, verify_url: str) -> None:
    send_email(
        to_email=to_email,
        subject="Verify your BudgetArc email",
        body=(
            "Welcome to BudgetArc.\n\n"
            "Use this one-time link to verify your email address and set your password:\n\n"
            f"{verify_url}\n\n"
            "This link expires in 24 hours. If you did not request this, you can ignore this email."
        ),
    )


def send_password_reset_email(*, to_email: str, reset_url: str) -> None:
    send_email(
        to_email=to_email,
        subject="Reset your BudgetArc password",
        body=(
            "Use this one-time link to reset your BudgetArc password:\n\n"
            f"{reset_url}\n\n"
            "This link expires in 60 minutes. If you did not request this, you can ignore this email."
        ),
    )
