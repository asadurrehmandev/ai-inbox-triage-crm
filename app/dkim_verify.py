"""Check DKIM signatures on the raw RFC822 message.

The webhook JSON path has no raw message, so this returns None there and the
filing gate uses TRUSTED_AUTHSERV_ID instead. When dkimpy is installed and
the bytes are present, every signature is checked. One passing signature whose
domain aligns with From is enough. A header claiming dkim=pass cannot satisfy
this check.
"""

from __future__ import annotations

import logging

log = logging.getLogger("lane.dkim")


def _domain(verifier) -> str:
    domain = getattr(verifier, "domain", None)
    if isinstance(domain, bytes):
        domain = domain.decode("ascii", "replace")
    return (domain or "").strip().lower().strip(".")


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
    except Exception:
        log.warning("dkim_verify_failed", exc_info=True)
        return []
    signatures = [
        pair
        for pair in getattr(verifier, "headers", []) or []
        if pair and isinstance(pair[0], bytes) and pair[0].lower() == b"dkim-signature"
    ]
    if not signatures:
        return []
    found: list[str] = []
    for index in range(len(signatures)):
        try:
            passed = bool(verifier.verify(index))
        except Exception:
            log.warning("dkim_verify_failed index=%s", index, exc_info=True)
            continue
        if not passed:
            continue
        host = _domain(verifier)
        if host and host not in found:
            found.append(host)
    return found
