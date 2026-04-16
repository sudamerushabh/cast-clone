"""AI provider configuration service.

Manages the runtime AI configuration: reading from DB (with env-var fallback),
encrypting/decrypting secrets, listing models from Bedrock/OpenAI, and testing
provider connections.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

import boto3
import structlog
from anthropic import AsyncAnthropicBedrock
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.fernet import Fernet
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.db import AiConfig

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Encryption helpers (shared Fernet key derivation with email service)
# ---------------------------------------------------------------------------

def _derive_fernet_key(secret_key: str) -> bytes:
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str) -> bytes:
    settings = get_settings()
    f = Fernet(_derive_fernet_key(settings.secret_key))
    return f.encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    settings = get_settings()
    f = Fernet(_derive_fernet_key(settings.secret_key))
    return f.decrypt(ciphertext).decode()


# ---------------------------------------------------------------------------
# Effective config (DB + env-var merge)
# ---------------------------------------------------------------------------

@dataclass
class EffectiveAiConfig:
    """Resolved AI configuration — DB values override env-var defaults."""

    provider: str
    # Bedrock
    aws_region: str
    bedrock_use_iam_role: bool
    aws_access_key_id: str | None
    aws_secret_access_key: str | None  # decrypted
    # OpenAI
    openai_api_key: str | None  # decrypted
    openai_base_url: str | None
    # Model assignments
    chat_model: str
    pr_analysis_model: str
    summary_model: str
    # Advanced params
    temperature: float
    top_p: float
    max_response_tokens: int
    thinking_budget_tokens: int
    chat_timeout_seconds: int
    max_tool_calls: int
    # Cost
    cost_input_per_mtok: float
    cost_output_per_mtok: float


async def get_ai_config(session: AsyncSession) -> EffectiveAiConfig:
    """Read AI config from DB, falling back to env vars for unset fields."""
    settings = get_settings()

    result = await session.execute(select(AiConfig).limit(1))
    row = result.scalar_one_or_none()

    if row is None:
        return _config_from_env(settings)

    # Decrypt secrets
    aws_secret = None
    if row.aws_secret_access_key_encrypted:
        try:
            aws_secret = decrypt_secret(row.aws_secret_access_key_encrypted)
        except Exception:
            await logger.awarning("ai_config.decrypt_aws_secret_failed")

    openai_key = None
    if row.openai_api_key_encrypted:
        try:
            openai_key = decrypt_secret(row.openai_api_key_encrypted)
        except Exception:
            await logger.awarning("ai_config.decrypt_openai_key_failed")

    return EffectiveAiConfig(
        provider=row.provider,
        aws_region=row.aws_region,
        bedrock_use_iam_role=row.bedrock_use_iam_role,
        aws_access_key_id=row.aws_access_key_id,
        aws_secret_access_key=aws_secret,
        openai_api_key=openai_key,
        openai_base_url=row.openai_base_url,
        chat_model=row.chat_model,
        pr_analysis_model=row.pr_analysis_model,
        summary_model=row.summary_model,
        temperature=float(row.temperature),
        top_p=float(row.top_p),
        max_response_tokens=row.max_response_tokens,
        thinking_budget_tokens=row.thinking_budget_tokens,
        chat_timeout_seconds=row.chat_timeout_seconds,
        max_tool_calls=row.max_tool_calls,
        cost_input_per_mtok=float(row.cost_input_per_mtok),
        cost_output_per_mtok=float(row.cost_output_per_mtok),
    )


def _config_from_env(settings: Settings) -> EffectiveAiConfig:
    """Build config purely from environment variables."""
    return EffectiveAiConfig(
        provider="bedrock",
        aws_region=settings.aws_region,
        bedrock_use_iam_role=True,
        aws_access_key_id=None,
        aws_secret_access_key=None,
        openai_api_key=None,
        openai_base_url=None,
        chat_model=settings.chat_model,
        pr_analysis_model=settings.pr_analysis_model,
        summary_model=settings.summary_model,
        temperature=1.0,
        top_p=1.0,
        max_response_tokens=settings.chat_max_response_tokens,
        thinking_budget_tokens=settings.chat_thinking_budget_tokens,
        max_tool_calls=settings.chat_max_tool_calls,
        chat_timeout_seconds=settings.chat_timeout_seconds,
        cost_input_per_mtok=settings.ai_cost_input_per_mtok,
        cost_output_per_mtok=settings.ai_cost_output_per_mtok,
    )


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------

def create_bedrock_client(config: EffectiveAiConfig) -> AsyncAnthropicBedrock:
    """Create an AsyncAnthropicBedrock client from effective config."""
    kwargs: dict[str, Any] = {"aws_region": config.aws_region}
    if not config.bedrock_use_iam_role and config.aws_access_key_id:
        kwargs["aws_access_key"] = config.aws_access_key_id
        kwargs["aws_secret_key"] = config.aws_secret_access_key or ""
    return AsyncAnthropicBedrock(**kwargs)


def create_openai_client(config: EffectiveAiConfig) -> AsyncOpenAI:
    """Create an AsyncOpenAI client from effective config."""
    kwargs: dict[str, Any] = {}
    if config.openai_api_key:
        kwargs["api_key"] = config.openai_api_key
    if config.openai_base_url:
        kwargs["base_url"] = config.openai_base_url
    return AsyncOpenAI(**kwargs)


# ---------------------------------------------------------------------------
# Model listing
# ---------------------------------------------------------------------------

@dataclass
class ModelInfo:
    model_id: str
    name: str
    provider_name: str
    supports_streaming: bool = True
    supports_tool_use: bool = True


async def list_bedrock_models(config: EffectiveAiConfig) -> list[ModelInfo]:
    """List available foundation models from AWS Bedrock."""
    try:
        kwargs: dict[str, Any] = {"region_name": config.aws_region}
        if not config.bedrock_use_iam_role and config.aws_access_key_id:
            kwargs["aws_access_key_id"] = config.aws_access_key_id
            kwargs["aws_secret_access_key"] = config.aws_secret_access_key or ""

        client = boto3.client("bedrock", **kwargs)
        response = client.list_foundation_models(byOutputModality="TEXT")

        models: list[ModelInfo] = []
        for m in response.get("modelSummaries", []):
            model_id = m.get("modelId", "")
            name = m.get("modelName", model_id)
            provider = m.get("providerName", "Unknown")
            streaming = "STREAMING" in m.get("responseStreamingSupported", "")
            # Bedrock models generally support streaming
            models.append(ModelInfo(
                model_id=model_id,
                name=name,
                provider_name=provider,
                supports_streaming=streaming or True,
                supports_tool_use="TOOL_USE" in str(m.get("inferenceTypesSupported", [])),
            ))

        # Also add cross-region inference profiles (us.anthropic.* pattern)
        try:
            paginator = client.get_paginator("list_inference_profiles")
            for page in paginator.paginate():
                for profile in page.get("inferenceProfileSummaries", []):
                    pid = profile.get("inferenceProfileId", "")
                    pname = profile.get("inferenceProfileName", pid)
                    models.append(ModelInfo(
                        model_id=pid,
                        name=f"{pname} (cross-region)",
                        provider_name="Anthropic",
                        supports_streaming=True,
                        supports_tool_use=True,
                    ))
        except (BotoCoreError, ClientError):
            pass  # inference profiles API may not be available in all regions

        return sorted(models, key=lambda m: m.name)
    except (BotoCoreError, ClientError) as exc:
        await logger.aerror("ai_provider.list_bedrock_models_failed", error=str(exc))
        raise


async def list_openai_models(config: EffectiveAiConfig) -> list[ModelInfo]:
    """List available models from OpenAI."""
    try:
        client = create_openai_client(config)
        response = await client.models.list()

        # Filter to chat-capable models
        chat_prefixes = ("gpt-4", "gpt-3.5", "o1", "o3", "o4")
        models: list[ModelInfo] = []
        for m in response.data:
            if any(m.id.startswith(p) for p in chat_prefixes):
                models.append(ModelInfo(
                    model_id=m.id,
                    name=m.id,
                    provider_name="OpenAI",
                    supports_streaming=True,
                    supports_tool_use=not m.id.startswith("o1-mini"),
                ))

        return sorted(models, key=lambda m: m.name)
    except Exception as exc:
        await logger.aerror("ai_provider.list_openai_models_failed", error=str(exc))
        raise


async def list_models(config: EffectiveAiConfig) -> list[ModelInfo]:
    """List available models for the active provider."""
    if config.provider == "openai":
        return await list_openai_models(config)
    return await list_bedrock_models(config)


# ---------------------------------------------------------------------------
# Connection testing
# ---------------------------------------------------------------------------

async def test_bedrock_connection(config: EffectiveAiConfig) -> tuple[bool, str]:
    """Test Bedrock credentials by listing models."""
    try:
        kwargs: dict[str, Any] = {"region_name": config.aws_region}
        if not config.bedrock_use_iam_role and config.aws_access_key_id:
            kwargs["aws_access_key_id"] = config.aws_access_key_id
            kwargs["aws_secret_access_key"] = config.aws_secret_access_key or ""

        client = boto3.client("bedrock", **kwargs)
        resp = client.list_foundation_models(byOutputModality="TEXT")
        count = len(resp.get("modelSummaries", []))
        return True, f"Connected. {count} models available in {config.aws_region}."
    except (BotoCoreError, ClientError) as exc:
        return False, str(exc)


async def test_openai_connection(config: EffectiveAiConfig) -> tuple[bool, str]:
    """Test OpenAI credentials by listing models."""
    try:
        client = create_openai_client(config)
        response = await client.models.list()
        count = len(response.data)
        return True, f"Connected. {count} models available."
    except Exception as exc:
        return False, str(exc)


async def test_connection(config: EffectiveAiConfig) -> tuple[bool, str]:
    """Test the active provider's connection."""
    if config.provider == "openai":
        return await test_openai_connection(config)
    return await test_bedrock_connection(config)
