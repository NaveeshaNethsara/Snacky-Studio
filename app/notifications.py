"""Outbound notifications engine supporting Slack, Discord, and SMTP email."""
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def send_slack_notification(webhook_url: str, title: str, message: str, details: Optional[dict[str, Any]] = None) -> bool:
    """Send formatted alert to Slack incoming webhook."""
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": message}},
    ]
    if details:
        fields = [{"type": "mrkdwn", "text": f"*{k}:*\n`{v}`"} for k, v in list(details.items())[:10]]
        blocks.append({"type": "section", "fields": fields})

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(webhook_url, json={"blocks": blocks})
            return resp.status_code == 200
    except Exception as exc:
        logger.warning("Failed to dispatch Slack notification: %s", exc)
        return False


def send_discord_notification(webhook_url: str, title: str, message: str, details: Optional[dict[str, Any]] = None) -> bool:
    """Send embed alert to Discord incoming webhook."""
    embed = {
        "title": title,
        "description": message,
        "color": 0x34D399 if "completed" in title.lower() else 0xEF4444,
    }
    if details:
        embed["fields"] = [{"name": str(k), "value": str(v), "inline": True} for k, v in list(details.items())[:10]]

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(webhook_url, json={"embeds": [embed]})
            return resp.status_code in (200, 204)
    except Exception as exc:
        logger.warning("Failed to dispatch Discord notification: %s", exc)
        return False


def send_email_notification(
    smtp_host: str,
    smtp_port: int,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> bool:
    """Send transactional notification email."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10.0) as server:
            server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(msg)
            return True
    except Exception as exc:
        logger.warning("Failed to send notification email to %s: %s", recipient, exc)
        return False

