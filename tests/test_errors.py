from __future__ import annotations

from aep_monitor.errors import friendly_error


def test_connection_failure_is_classified_and_retryable():
    info = friendly_error(RuntimeError("Cannot connect to Adobe. Check VPN, proxy, and firewall. Endpoint: https://x"))
    assert info.title == "Adobe connection failed"
    assert info.reasons
    assert info.retryable is True


def test_missing_configuration_is_not_retryable():
    info = friendly_error(RuntimeError("https://x client is not configured — missing org id, client id, secret, or scopes."))
    assert info.title == "Adobe is not configured"
    assert info.retryable is False


def test_permission_denied_is_not_retryable():
    info = friendly_error(RuntimeError("Adobe returned HTTP 403: forbidden"))
    assert "permission denied" in info.title.lower()
    assert info.retryable is False


def test_aep_access_control_denial_is_distinguished_from_generic_permission_denied():
    """Regression: reported live against the SDR page's Schema Registry
    call — Adobe's real response body for a missing AEP-side Product
    Profile permission (distinct from a Developer Console scope issue).
    Getting this misclassified as the generic "credential/scope" bucket
    sends the user to fix the wrong thing."""
    raw_response = (
        'Adobe returned HTTP 403: {"type":http://ns.adobe.com/aep/errors/XDM-2010-403,'
        '"title":"Permission management access denied","status":403,'
        '"report":{"registryRequestId":"1103ab55-da1e-43f9-b609-1bbb176bd1be",'
        '"timestamp":"08-24-2026 04:41:21",'
        '"detailed-message":"GET access is denied for this resource from access control.","sub-errors":[]},'
        '"detail":"GET access is denied for this resource from access control."}'
    )
    info = friendly_error(RuntimeError(raw_response))
    assert "admin console permission" in info.title.lower()
    assert any("product profile" in reason.lower() for reason in info.reasons)
    assert info.retryable is False


def test_rate_limit_is_retryable():
    info = friendly_error(RuntimeError("Adobe returned HTTP 429: too many requests"))
    assert "rate-limiting" in info.title.lower()
    assert info.retryable is True


def test_timeout_is_retryable():
    info = friendly_error(RuntimeError("Adobe request timed out. Endpoint: https://x"))
    assert info.title == "Adobe request timed out"
    assert info.retryable is True


def test_server_error_is_retryable():
    info = friendly_error(RuntimeError("Adobe returned HTTP 500: internal error"))
    assert info.title == "Adobe returned a server error"
    assert info.retryable is True


def test_not_found_is_not_retryable():
    info = friendly_error(RuntimeError("not found"))
    assert info.title == "Not found"
    assert info.retryable is False


def test_unknown_error_falls_back_to_generic_message():
    info = friendly_error(ValueError("something obscure happened"))
    assert info.title == "Something went wrong"
    assert info.reasons == ["something obscure happened"]
