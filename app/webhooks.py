"""Transactional webhook delivery engine with SSRF validation, HMAC signing, and exponential backoff/jitter."""
import hashlib
import hmac
import ipaddress
import json
import logging
import random
import socket
import time
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

MAX_WEBHOOK_ATTEMPTS = 5
WEBHOOK_TIMEOUT_SECONDS = 10.0


class WebhookSSRFError(ValueError):
    """Raised when a webhook target URL points to a forbidden network address."""
    pass


def validate_webhook_url(url: str) -> str:
    """Validate that the webhook target is HTTP(S) and does not point to internal/private CIDRs."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise WebhookSSRFError("Webhook target URL must use http or https scheme.")
    hostname = parsed.hostname
    if not hostname:
        raise WebhookSSRFError("Webhook target URL has no hostname.")

    # Disallow localhost / metadata names
    if hostname.lower() in ("localhost", "metadata.google.internal", "instance-data"):
        raise WebhookSSRFError(f"Target host '{hostname}' is not permitted.")

    try:
        # Resolve all IPs for the host
        addr_infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebhookSSRFError(f"Could not resolve host '{hostname}': {exc}") from exc

    if not addr_infos:
        raise WebhookSSRFError(f"No IP addresses found for '{hostname}'.")

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if ip.is_loopback or ip.is_private or ip.is_reserved or ip.is_link_local or ip.is_multicast:
            raise WebhookSSRFError(f"Target IP address '{ip_str}' is within a private or forbidden range.")
        # Explicitly guard against AWS/GCP/Azure link-local metadata (169.254.169.254)
        if str(ip) == "169.254.169.254":
            raise WebhookSSRFError("Target IP address is a cloud instance metadata endpoint.")

    return url


def sign_payload(secret: str, timestamp: float, raw_body: bytes) -> str:
    """Sign timestamp + raw body using HMAC-SHA256 for replay protection."""
    message = f"{int(timestamp)}.".encode("utf-8") + raw_body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def calculate_backoff(attempt: int) -> float:
    """Calculate exponential backoff with jitter: min(3600, 2^attempt * 10 + jitter)."""
    base = (2 ** attempt) * 10
    jitter = random.uniform(0.5, 5.0)
    return min(3600.0, base + jitter)


def deliver_webhook(delivery: dict, store) -> bool:
    """Execute delivery attempt for a single queued webhook row."""
    delivery_id = delivery["id"]
    target_url = delivery["target_url"]
    secret = delivery["secret"]
    event = delivery["event"]
    payload = delivery["payload"]
    attempt_count = delivery.get("attempt_count", 0)

    try:
        validate_webhook_url(target_url)
    except WebhookSSRFError as exc:
        logger.warning("SSRF check blocked webhook %s to %s: %s", delivery_id, target_url, exc)
        store.record_webhook_delivery_attempt(
            delivery_id=delivery_id,
            success=False,
            status_code=None,
            response_body=f"SSRF blocked: {exc}",
            next_attempt_at=None,  # Do not retry SSRF violations
        )
        return False

    now = time.time()
    body_data = {
        "event": event,
        "delivery_id": delivery_id,
        "timestamp": now,
        "data": payload,
    }
    raw_body = json.dumps(body_data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = sign_payload(secret, now, raw_body)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Snacky-Webhooks/1.0",
        "X-Snacky-Event": event,
        "X-Snacky-Delivery": delivery_id,
        "X-Snacky-Timestamp": str(int(now)),
        "X-Snacky-Signature": f"sha256={signature}",
    }

    try:
        with httpx.Client(timeout=WEBHOOK_TIMEOUT_SECONDS, follow_redirects=False) as client:
            resp = client.post(target_url, content=raw_body, headers=headers)
            status_code = resp.status_code
            resp_text = resp.text[:1000]
            success = 200 <= status_code < 300

            if success:
                store.record_webhook_delivery_attempt(
                    delivery_id=delivery_id,
                    success=True,
                    status_code=status_code,
                    response_body=resp_text,
                    next_attempt_at=None,
                )
                return True
            else:
                next_attempt = None
                if attempt_count + 1 < MAX_WEBHOOK_ATTEMPTS:
                    next_attempt = now + calculate_backoff(attempt_count + 1)
                store.record_webhook_delivery_attempt(
                    delivery_id=delivery_id,
                    success=False,
                    status_code=status_code,
                    response_body=resp_text,
                    next_attempt_at=next_attempt,
                )
                return False
    except Exception as exc:
        logger.info("Webhook %s HTTP delivery failure: %s", delivery_id, exc)
        next_attempt = None
        if attempt_count + 1 < MAX_WEBHOOK_ATTEMPTS:
            next_attempt = now + calculate_backoff(attempt_count + 1)
        store.record_webhook_delivery_attempt(
            delivery_id=delivery_id,
            success=False,
            status_code=None,
            response_body=str(exc)[:1000],
            next_attempt_at=next_attempt,
        )
        return False


def dispatch_due_webhooks(store, limit: int = 20) -> int:
    """Fetch due webhooks and deliver them."""
    due = store.get_due_webhook_deliveries(limit=limit)
    dispatched = 0
    for row in due:
        deliver_webhook(row, store)
        dispatched += 1
    return dispatched

