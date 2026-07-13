"""Map adapter-native failures onto the kernel's stable transport taxonomy."""

from __future__ import annotations

from boltrig.adapters.base import AdapterError, ErrorClass
from boltrig.models import AdapterFailure

_TRANSPORT_ERRORS = {
    ErrorClass.NOT_FOUND: (404, "adapter_not_found"),
    ErrorClass.UNAUTHORISED: (403, "adapter_unauthorised"),
    ErrorClass.INVALID: (400, "adapter_invalid"),
    ErrorClass.CONFLICT: (409, "adapter_conflict"),
    ErrorClass.INTERNAL: (502, "adapter_internal"),
}


def adapter_failure(error: AdapterError | None) -> AdapterFailure:
    """Return a redaction-friendly kernel error for a failed adapter result."""
    if error is None:
        return AdapterFailure(
            "adapter returned no error detail",
            status_code=502,
            reason="adapter_internal",
        )
    status_code, reason = _TRANSPORT_ERRORS.get(error.error_class, (502, "adapter_internal"))
    return AdapterFailure(error.message, status_code=status_code, reason=reason)
