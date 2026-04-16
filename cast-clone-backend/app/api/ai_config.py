"""AI provider configuration endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.models.db import AiConfig, User
from app.services.activity import log_activity
from app.services.ai_provider import (
    EffectiveAiConfig,
    ModelInfo,
    decrypt_secret,
    encrypt_secret,
    get_ai_config,
    list_models,
    test_connection,
)
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["ai-config"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AiConfigResponse(BaseModel):
    provider: str
    # Bedrock
    aws_region: str
    bedrock_use_iam_role: bool
    aws_access_key_id: str | None
    has_aws_secret_key: bool
    # OpenAI
    has_openai_api_key: bool
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


class AiConfigUpdateRequest(BaseModel):
    provider: str = "bedrock"
    # Bedrock
    aws_region: str = "us-east-1"
    bedrock_use_iam_role: bool = True
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None  # "***" = keep existing
    # OpenAI
    openai_api_key: str | None = None  # "***" = keep existing
    openai_base_url: str | None = None
    # Model assignments
    chat_model: str = "us.anthropic.claude-sonnet-4-6"
    pr_analysis_model: str = "us.anthropic.claude-sonnet-4-6"
    summary_model: str = "us.anthropic.claude-sonnet-4-6"
    # Advanced params
    temperature: float = 1.0
    top_p: float = 1.0
    max_response_tokens: int = 4096
    thinking_budget_tokens: int = 2048
    chat_timeout_seconds: int = 120
    max_tool_calls: int = 15
    # Cost
    cost_input_per_mtok: float = 3.0
    cost_output_per_mtok: float = 15.0


class ModelInfoResponse(BaseModel):
    model_id: str
    name: str
    provider_name: str
    supports_streaming: bool
    supports_tool_use: bool


class ModelsListResponse(BaseModel):
    provider: str
    models: list[ModelInfoResponse]


class TestConnectionRequest(BaseModel):
    provider: str = "bedrock"
    aws_region: str = "us-east-1"
    bedrock_use_iam_role: bool = True
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config_to_response(row: AiConfig) -> AiConfigResponse:
    return AiConfigResponse(
        provider=row.provider,
        aws_region=row.aws_region,
        bedrock_use_iam_role=row.bedrock_use_iam_role,
        aws_access_key_id=row.aws_access_key_id,
        has_aws_secret_key=row.aws_secret_access_key_encrypted is not None,
        has_openai_api_key=row.openai_api_key_encrypted is not None,
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


_DEFAULT_RESPONSE = AiConfigResponse(
    provider="bedrock",
    aws_region="us-east-1",
    bedrock_use_iam_role=True,
    aws_access_key_id=None,
    has_aws_secret_key=False,
    has_openai_api_key=False,
    openai_base_url=None,
    chat_model="us.anthropic.claude-sonnet-4-6",
    pr_analysis_model="us.anthropic.claude-sonnet-4-6",
    summary_model="us.anthropic.claude-sonnet-4-6",
    temperature=1.0,
    top_p=1.0,
    max_response_tokens=4096,
    thinking_budget_tokens=2048,
    chat_timeout_seconds=120,
    max_tool_calls=15,
    cost_input_per_mtok=3.0,
    cost_output_per_mtok=15.0,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/config", response_model=AiConfigResponse)
async def get_config(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AiConfigResponse:
    result = await session.execute(select(AiConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        return _DEFAULT_RESPONSE
    return _config_to_response(config)


@router.put("/config", response_model=AiConfigResponse)
async def update_config(
    body: AiConfigUpdateRequest,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AiConfigResponse:
    result = await session.execute(select(AiConfig).limit(1))
    config = result.scalar_one_or_none()

    if config is None:
        config = AiConfig()
        session.add(config)

    # Update all fields
    config.provider = body.provider
    config.aws_region = body.aws_region
    config.bedrock_use_iam_role = body.bedrock_use_iam_role
    config.aws_access_key_id = body.aws_access_key_id
    config.openai_base_url = body.openai_base_url
    config.chat_model = body.chat_model
    config.pr_analysis_model = body.pr_analysis_model
    config.summary_model = body.summary_model
    config.temperature = body.temperature
    config.top_p = body.top_p
    config.max_response_tokens = body.max_response_tokens
    config.thinking_budget_tokens = body.thinking_budget_tokens
    config.chat_timeout_seconds = body.chat_timeout_seconds
    config.max_tool_calls = body.max_tool_calls
    config.cost_input_per_mtok = body.cost_input_per_mtok
    config.cost_output_per_mtok = body.cost_output_per_mtok

    # AWS secret: "***" = preserve existing, empty = clear, anything else = encrypt
    if body.aws_secret_access_key != "***":
        if body.aws_secret_access_key:
            config.aws_secret_access_key_encrypted = encrypt_secret(
                body.aws_secret_access_key
            )
        else:
            config.aws_secret_access_key_encrypted = None

    # OpenAI key: same pattern
    if body.openai_api_key != "***":
        if body.openai_api_key:
            config.openai_api_key_encrypted = encrypt_secret(body.openai_api_key)
        else:
            config.openai_api_key_encrypted = None

    await session.commit()
    await session.refresh(config)

    await log_activity(
        session, "settings.ai_updated", user_id=_admin.id,
        resource_type="settings", resource_id="ai_config",
        details={"provider": body.provider, "chat_model": body.chat_model},
    )

    return _config_to_response(config)


@router.get("/models", response_model=ModelsListResponse)
async def get_models(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ModelsListResponse:
    config = await get_ai_config(session)
    models = await list_models(config)
    return ModelsListResponse(
        provider=config.provider,
        models=[
            ModelInfoResponse(
                model_id=m.model_id,
                name=m.name,
                provider_name=m.provider_name,
                supports_streaming=m.supports_streaming,
                supports_tool_use=m.supports_tool_use,
            )
            for m in models
        ],
    )


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_provider_connection(
    body: TestConnectionRequest,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TestConnectionResponse:
    # Build ephemeral config from request body (don't read DB — test what user provided)
    # For "***" secrets, fall back to DB-stored values
    existing = await get_ai_config(session)

    aws_secret = body.aws_secret_access_key
    if aws_secret == "***":
        aws_secret = existing.aws_secret_access_key

    openai_key = body.openai_api_key
    if openai_key == "***":
        openai_key = existing.openai_api_key

    test_config = EffectiveAiConfig(
        provider=body.provider,
        aws_region=body.aws_region,
        bedrock_use_iam_role=body.bedrock_use_iam_role,
        aws_access_key_id=body.aws_access_key_id,
        aws_secret_access_key=aws_secret,
        openai_api_key=openai_key,
        openai_base_url=body.openai_base_url,
        # Model/param fields don't matter for connection test
        chat_model="",
        pr_analysis_model="",
        summary_model="",
        temperature=1.0,
        top_p=1.0,
        max_response_tokens=4096,
        thinking_budget_tokens=2048,
        chat_timeout_seconds=120,
        max_tool_calls=15,
        cost_input_per_mtok=3.0,
        cost_output_per_mtok=15.0,
    )

    success, message = await test_connection(test_config)
    return TestConnectionResponse(success=success, message=message)
