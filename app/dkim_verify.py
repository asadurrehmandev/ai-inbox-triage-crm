"""Check a DKIM signature on the raw RFC822 message.

The webhook JSON path has no raw message, so this returns None there and the
filing gate uses TRUSTED_AUTHSERV_ID instead. When dkimpy is installed and
the bytes are present, a passing signature is the only DKIM result that counts.
A header claiming dkim=pass cannot satisfy this check.
"""

from __future__ import annotations

import logging

log = logging.getLogger("lane.dkim")


def verified_dkim_domains(raw: bytes) -> list[str] | None:
    """Domains with a passing DKIM signature.

    None means dkimpy is not installed, so the caller may fall back to a
    trusted Authentication-Results header. An empty list means the bytes were
    checked and no signature passed.
    """
    if not raw:
        return []
    try:
        import dkim
    except ImportError:
        return None
    try:
        verifier = dkim.DKIM(raw, timeout=5)
        passed = bool(verifier.verify())
    except Exception:
        log.warning("dkim_verify_failed", exc_info=True)
        return []
    if not passed:
        return []
    domain = getattr(verifier, "domain", None)
    if isinstance(domain, bytes):
        domain = domain.decode("ascii", "replace")
    host = (domain or "").strip().lower().strip(".")
    return [host] if host else []
