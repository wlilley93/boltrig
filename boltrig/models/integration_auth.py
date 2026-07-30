"""Closed authentication contracts for certified integration providers.

These are deliberately narrower than JSON Schema.  A reviewed provider may
declare a finite list of string fields and identify which non-secret fields
name the connected account.  The setup route accepts exactly those names.
There is no arbitrary object or provider-controlled validation code at the
credential boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


INTEGRATION_SECRET_INPUT_KINDS = (
    "api_key",
    "password",
    "text",
    "token",
    "username",
)
INTEGRATION_CREDENTIAL_KINDS = ("api_key", "basic", "token")
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_FIELD_LENGTH = 4096
_MAX_CONTRACT_FIELDS = 12


@dataclass(frozen=True)
class IntegrationSecretField:
    """One reviewed field in a manual authentication contract."""

    name: str
    label: str
    input_kind: str = "token"
    secret: bool = True
    required: bool = True
    min_length: int = 1
    max_length: int = 4096

    def __post_init__(self) -> None:
        if not _FIELD_NAME.fullmatch(self.name):
            raise ValueError("invalid integration secret field name")
        if not self.label.strip() or len(self.label) > 120:
            raise ValueError("invalid integration secret field label")
        if self.input_kind not in INTEGRATION_SECRET_INPUT_KINDS:
            raise ValueError("unsupported integration secret input kind")
        if not 0 <= self.min_length <= self.max_length <= _MAX_FIELD_LENGTH:
            raise ValueError("invalid integration secret field bounds")
        if self.required and self.min_length < 1:
            raise ValueError("required integration secret fields cannot be empty")


@dataclass(frozen=True)
class IntegrationSecretContract:
    """A versioned, closed manual-secret contract reviewed with the provider."""

    version: str
    credential_kind: str
    fields: tuple[IntegrationSecretField, ...]
    account_id_field: str | None = None
    account_label_field: str | None = None

    def __post_init__(self) -> None:
        if not _FIELD_NAME.fullmatch(self.version):
            raise ValueError("invalid integration secret contract version")
        if self.credential_kind not in INTEGRATION_CREDENTIAL_KINDS:
            raise ValueError("unsupported integration credential kind")
        if not 1 <= len(self.fields) <= _MAX_CONTRACT_FIELDS:
            raise ValueError("integration secret contract requires bounded fields")
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("integration secret contract field names must be unique")
        if not any(field.secret for field in self.fields):
            raise ValueError("integration secret contract must contain secret material")
        for account_field in (self.account_id_field, self.account_label_field):
            if account_field is None:
                continue
            if account_field not in names:
                raise ValueError("integration account field is not declared")
            field = self.fields[names.index(account_field)]
            if field.secret:
                raise ValueError("integration account labels cannot derive from secrets")
            if field.max_length > 200:
                raise ValueError("integration account labels must be bounded to 200 bytes")


def secret_contract_to_dict(contract: IntegrationSecretContract) -> dict[str, Any]:
    """Return the stable JSONB representation stored with reviewed catalogue data."""

    return {
        "version": contract.version,
        "credential_kind": contract.credential_kind,
        "fields": [
            {
                "name": field.name,
                "label": field.label,
                "input_kind": field.input_kind,
                "secret": field.secret,
                "required": field.required,
                "min_length": field.min_length,
                "max_length": field.max_length,
            }
            for field in contract.fields
        ],
        "account_id_field": contract.account_id_field,
        "account_label_field": contract.account_label_field,
    }


def secret_contract_from_dict(value: object) -> IntegrationSecretContract | None:
    """Parse only the closed persisted shape; any extra key fails certification."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("integration secret contract must be an object")
    allowed = {
        "version",
        "credential_kind",
        "fields",
        "account_id_field",
        "account_label_field",
    }
    if set(value) - allowed:
        raise ValueError("integration secret contract contains unknown keys")
    raw_fields = value.get("fields")
    if not isinstance(raw_fields, list):
        raise ValueError("integration secret contract fields must be a list")
    fields: list[IntegrationSecretField] = []
    field_keys = {
        "name",
        "label",
        "input_kind",
        "secret",
        "required",
        "min_length",
        "max_length",
    }
    for raw in raw_fields:
        if not isinstance(raw, dict) or set(raw) - field_keys:
            raise ValueError("integration secret field contains unknown keys")
        secret = raw.get("secret", True)
        required = raw.get("required", True)
        min_length = raw.get("min_length", 1)
        max_length = raw.get("max_length", _MAX_FIELD_LENGTH)
        if not isinstance(secret, bool) or not isinstance(required, bool):
            raise ValueError("integration secret field flags must be boolean")
        if (
            isinstance(min_length, bool)
            or not isinstance(min_length, int)
            or isinstance(max_length, bool)
            or not isinstance(max_length, int)
        ):
            raise ValueError("integration secret field bounds must be integers")
        fields.append(
            IntegrationSecretField(
                name=str(raw.get("name") or ""),
                label=str(raw.get("label") or ""),
                input_kind=str(raw.get("input_kind") or "token"),
                secret=secret,
                required=required,
                min_length=min_length,
                max_length=max_length,
            )
        )
    return IntegrationSecretContract(
        version=str(value.get("version") or ""),
        credential_kind=str(value.get("credential_kind") or ""),
        fields=tuple(fields),
        account_id_field=(
            str(value["account_id_field"])
            if value.get("account_id_field") is not None
            else None
        ),
        account_label_field=(
            str(value["account_label_field"])
            if value.get("account_label_field") is not None
            else None
        ),
    )


__all__ = [
    "INTEGRATION_CREDENTIAL_KINDS",
    "INTEGRATION_SECRET_INPUT_KINDS",
    "IntegrationSecretContract",
    "IntegrationSecretField",
    "secret_contract_from_dict",
    "secret_contract_to_dict",
]
