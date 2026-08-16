"""Deterministic catalogue definitions for reviewed first-party integrations.

Certification here covers the shipped adapter and its closed credential-input
contract.  It does not imply that a tenant has installed or activated the
adapter: the catalogue projection separately derives runtime availability from
the tenant's adapter record and live loader health.
"""

from __future__ import annotations

from datetime import UTC, datetime

from boltrig.models.integration_auth import (
    IntegrationSecretContract,
    IntegrationSecretField,
)
from boltrig.models.integrations import IntegrationCatalogueRecord


# A certification revision timestamp, not a boot timestamp.  Keeping it fixed
# makes repeated memory and Postgres reconciliation observably idempotent.
_CERTIFIED_AT = datetime(2026, 7, 30, tzinfo=UTC)
_AUDIO_CERTIFIED_AT = datetime(2026, 8, 15, tzinfo=UTC)


def certified_builtin_integrations(
    tenant_id: str,
) -> tuple[IntegrationCatalogueRecord, ...]:
    """Return the reviewed built-ins that have an executable setup contract."""

    return (
        _jira(tenant_id),
        _runpod(tenant_id),
        _xai_voice(tenant_id),
        _fish_audio(tenant_id),
        _deepgram_audio(tenant_id),
        _elevenlabs_audio(tenant_id),
        _openai_audio(tenant_id),
        _openai_compatible_audio(tenant_id),
    )


def _jira(tenant_id: str) -> IntegrationCatalogueRecord:
    return IntegrationCatalogueRecord(
        id="jira",
        tenant_id=tenant_id,
        label="Jira",
        category="work",
        transport="rest",
        auth=["manual_secret"],
        description=(
            "Create, read, update, search, and comment on Jira Cloud issues "
            "through governed ticket verbs."
        ),
        certification="certified",
        adapter_id="jira",
        secret_contract=IntegrationSecretContract(
            version="jira_cloud_v1",
            credential_kind="basic",
            fields=(
                IntegrationSecretField(
                    name="base_url",
                    label="Jira site URL",
                    input_kind="text",
                    secret=False,
                    min_length=12,
                    max_length=200,
                ),
                IntegrationSecretField(
                    name="username",
                    label="Atlassian account email",
                    input_kind="username",
                    min_length=3,
                    max_length=320,
                ),
                IntegrationSecretField(
                    name="api_token",
                    label="Atlassian API token",
                    input_kind="token",
                    min_length=8,
                    max_length=4096,
                ),
            ),
            account_id_field="base_url",
        ),
        setup_copy=(
            "Enter the Jira Cloud site URL, Atlassian account email, and "
            "API token. Secret fields are sealed and cannot be read back."
        ),
        access_copy=(
            "Boltrig receives only the Jira access granted to that Atlassian "
            "account; high-consequence writes remain governed."
        ),
        created_at=_CERTIFIED_AT,
        updated_at=_CERTIFIED_AT,
    )


def _runpod(tenant_id: str) -> IntegrationCatalogueRecord:
    return IntegrationCatalogueRecord(
        id="runpod",
        tenant_id=tenant_id,
        label="Runpod",
        category="analytics_operations",
        transport="rest",
        auth=["manual_secret"],
        description=("List and govern start, stop, and restart operations for Runpod pods."),
        certification="certified",
        adapter_id="runpod",
        secret_contract=IntegrationSecretContract(
            version="runpod_api_v1",
            credential_kind="api_key",
            fields=(
                IntegrationSecretField(
                    name="api_key",
                    label="Runpod API key",
                    input_kind="api_key",
                    min_length=8,
                    max_length=4096,
                ),
            ),
        ),
        setup_copy=("Enter a Runpod API key. It is sealed as a write-only credential."),
        access_copy=(
            "Pod reads and lifecycle actions use the key's Runpod permissions; "
            "mutating actions remain governed."
        ),
        created_at=_CERTIFIED_AT,
        updated_at=_CERTIFIED_AT,
    )


def _xai_voice(tenant_id: str) -> IntegrationCatalogueRecord:
    return IntegrationCatalogueRecord(
        id="xai-voice",
        tenant_id=tenant_id,
        label="xAI Voice",
        category="communications",
        transport="rest",
        auth=["manual_secret"],
        description=(
            "List voices, transcribe clips, and synthesise governed speech "
            "through xAI's REST voice adapter."
        ),
        certification="certified",
        adapter_id="xai-voice",
        secret_contract=IntegrationSecretContract(
            version="xai_voice_v1",
            credential_kind="api_key",
            fields=(
                IntegrationSecretField(
                    name="api_key",
                    label="xAI API key",
                    input_kind="api_key",
                    min_length=8,
                    max_length=4096,
                ),
            ),
        ),
        setup_copy=("Enter an xAI API key. It is sealed as a write-only credential."),
        access_copy=(
            "Speech requests use the key's xAI account and remain subject to "
            "Boltrig grants, approvals, limits, and audit."
        ),
        created_at=_CERTIFIED_AT,
        updated_at=_CERTIFIED_AT,
    )


def _audio_api_key(
    tenant_id: str,
    *,
    integration_id: str,
    adapter_id: str,
    label: str,
    description: str,
    access_copy: str,
    allow_base_url: bool = False,
) -> IntegrationCatalogueRecord:
    fields = [
        IntegrationSecretField(
            name="api_key",
            label=f"{label} API key",
            input_kind="api_key",
            min_length=8,
            max_length=4096,
        )
    ]
    if allow_base_url:
        fields.append(
            IntegrationSecretField(
                name="base_url",
                label="Dedicated API address",
                input_kind="text",
                secret=False,
                required=False,
                min_length=12,
                max_length=200,
            )
        )
    return IntegrationCatalogueRecord(
        id=integration_id,
        tenant_id=tenant_id,
        label=label,
        category="communications",
        transport="rest",
        auth=["manual_secret"],
        description=description,
        certification="certified",
        adapter_id=adapter_id,
        secret_contract=IntegrationSecretContract(
            version=f"{integration_id.replace('-', '_')}_v1",
            credential_kind="api_key",
            fields=tuple(fields),
        ),
        setup_copy=f"Enter a {label} API key.",
        access_copy=access_copy,
        created_at=_AUDIO_CERTIFIED_AT,
        updated_at=_AUDIO_CERTIFIED_AT,
    )


def _fish_audio(tenant_id: str) -> IntegrationCatalogueRecord:
    return _audio_api_key(
        tenant_id,
        integration_id="fish-audio",
        adapter_id="fish-audio",
        label="Fish Audio",
        description="Generate spoken replies with Fish Audio; transcription is available only when the deployment enables Fish ASR.",
        access_copy="Speech uses the permissions and credit on the connected Fish Audio account.",
    )


def _deepgram_audio(tenant_id: str) -> IntegrationCatalogueRecord:
    return _audio_api_key(
        tenant_id,
        integration_id="deepgram-audio",
        adapter_id="deepgram-audio",
        label="Deepgram",
        description="Transcribe audio and generate spoken replies with Deepgram.",
        access_copy="Speech uses the permissions and credit on the connected Deepgram project.",
        allow_base_url=True,
    )


def _elevenlabs_audio(tenant_id: str) -> IntegrationCatalogueRecord:
    return _audio_api_key(
        tenant_id,
        integration_id="elevenlabs-audio",
        adapter_id="elevenlabs-audio",
        label="ElevenLabs",
        description="Transcribe audio, browse voices, and generate spoken replies with ElevenLabs.",
        access_copy="Speech uses the permissions and credit on the connected ElevenLabs account.",
    )


def _openai_audio(tenant_id: str) -> IntegrationCatalogueRecord:
    return _audio_api_key(
        tenant_id,
        integration_id="openai-audio",
        adapter_id="openai-audio",
        label="OpenAI Audio",
        description="Transcribe audio and generate spoken replies with OpenAI's audio API.",
        access_copy="Speech uses the permissions and credit on the connected OpenAI project.",
    )


def _openai_compatible_audio(tenant_id: str) -> IntegrationCatalogueRecord:
    return IntegrationCatalogueRecord(
        id="openai-compatible-audio",
        tenant_id=tenant_id,
        label="Local or custom",
        category="communications",
        transport="rest",
        auth=["manual_secret"],
        description=(
            "Use a server-reachable OpenAI-compatible speech endpoint for "
            "transcription and spoken replies."
        ),
        certification="certified",
        adapter_id="openai-compatible-audio",
        secret_contract=IntegrationSecretContract(
            version="openai_compatible_audio_v1",
            credential_kind="api_key",
            fields=(
                IntegrationSecretField(
                    name="base_url",
                    label="HTTPS API address",
                    input_kind="text",
                    secret=False,
                    min_length=12,
                    max_length=200,
                ),
                IntegrationSecretField(
                    name="api_key",
                    label="Access key (if required)",
                    input_kind="api_key",
                    secret=True,
                    required=False,
                    min_length=0,
                    max_length=4096,
                ),
            ),
        ),
        setup_copy="Enter a server-reachable HTTPS API address and an access key only if that service requires one.",
        access_copy=(
            "Hosted Boltrig can reach only an endpoint exposed to its server. "
            "Private on-device audio should use Boltrig Desktop instead."
        ),
        created_at=_AUDIO_CERTIFIED_AT,
        updated_at=_AUDIO_CERTIFIED_AT,
    )


async def provision_builtin_integration_catalogue(store, tenant_id: str) -> None:
    """Reconcile reviewed definitions without touching any other catalogue row."""

    for item in certified_builtin_integrations(tenant_id):
        await store.upsert_integration_catalogue(item)


__all__ = [
    "certified_builtin_integrations",
    "provision_builtin_integration_catalogue",
]
