from __future__ import annotations

"""Turn raw exception text into a title + a short list of likely causes.

Kept framework-agnostic (no Streamlit import) so it stays unit-testable; the
UI wraps this with a small renderer in ui/shared.py.
"""

from dataclasses import dataclass, field


class AdobeRateLimitError(RuntimeError):
    """Raised specifically for Adobe HTTP 429 responses.

    Carries the `Retry-After` header (seconds) when Adobe sends one, so
    retry.call_with_retry can wait exactly as long as Adobe asked instead of
    guessing with blind exponential backoff. `retry_after` is None when the
    header was absent or unparsable, in which case the caller falls back to
    the normal backoff schedule.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class FriendlyError:
    title: str
    reasons: list[str] = field(default_factory=list)
    retryable: bool = True


_CONNECTION_REASONS = [
    "VPN is disconnected",
    "Adobe is temporarily unavailable",
    "A corporate proxy or firewall is blocking the request",
]
_TIMEOUT_REASONS = [
    "Adobe is slow to respond right now",
    "Network latency on VPN or proxy",
    "The request covered more data than usual",
]
_AUTH_REASONS = [
    "The credential's client secret expired or was rotated",
    "The organization ID does not match this credential",
    "The requested API/product isn't added to this credential's Developer Console project",
]
# Distinct from _AUTH_REASONS: this is Adobe's own AEP-side RBAC (Admin
# Console → Product Profiles → Permissions → Sandboxes), which gates read
# access to specific resources (schemas, datasets, ...) per sandbox —
# entirely separate from what APIs are added to the Developer Console
# project. A credential can pass every Developer Console check and still
# get this, resource by resource, if its Product Profile wasn't also
# granted access to that resource. Confirmed against a real Adobe response
# (error type XDM-2010-403) while building the SDR page's Schema Registry
# integration — "the API/product isn't granted" (the generic auth reason
# above) is the wrong diagnosis for this specific error shape.
_ACCESS_CONTROL_REASONS = [
    "The credential's Product Profile doesn't have this resource (e.g. Schemas) granted for this sandbox — "
    "Admin Console → Products → Adobe Experience Platform → Product Profiles → the profile tied to this "
    "credential's technical account → Permissions → Sandboxes → grant access for ADOBE_SANDBOX",
    "This is separate from adding the API in Developer Console — that grants the *scope*, this grants the "
    "*resource*, and both are required",
    "Permission changes can take a few minutes to propagate — retry shortly after granting access",
]
_CONFIG_REASONS = [
    "ADOBE_ORG_ID, ADOBE_CLIENT_ID, ADOBE_CLIENT_SECRET, or ADOBE_SCOPES is missing from .env",
    "The app was not restarted after .env was last edited",
]


def friendly_error(exc: BaseException) -> FriendlyError:
    message = str(exc).strip()
    lowered = message.lower()

    if "not configured" in lowered or "credentials are incomplete" in lowered:
        return FriendlyError("Adobe is not configured", _CONFIG_REASONS, retryable=False)
    if "cannot connect" in lowered:
        return FriendlyError("Adobe connection failed", _CONNECTION_REASONS)
    if "timed out" in lowered or "timeout" in lowered:
        return FriendlyError("Adobe request timed out", _TIMEOUT_REASONS)
    if "access control" in lowered or "permission management access denied" in lowered or "xdm-2010" in lowered:
        return FriendlyError("AEP denied access to this resource (Admin Console permission, not a Developer Console scope issue)", _ACCESS_CONTROL_REASONS, retryable=False)
    if "http 401" in lowered or "http 403" in lowered:
        return FriendlyError("Adobe rejected the request (permission denied)", _AUTH_REASONS, retryable=False)
    if "http 429" in lowered:
        return FriendlyError(
            "Adobe is rate-limiting requests",
            [
                "Too many requests were sent in a short period. Wait a moment and retry.",
                "Lower \"Requests/sec\" on the Settings page.",
            ],
        )
    if "http 5" in lowered and "adobe returned http 5" in lowered:
        return FriendlyError("Adobe returned a server error", ["Adobe is having a temporary issue on their end."])
    if "not found" in lowered:
        return FriendlyError("Not found", [message] if message else [], retryable=False)

    return FriendlyError("Something went wrong", [message] if message else ["An unexpected error occurred."])
