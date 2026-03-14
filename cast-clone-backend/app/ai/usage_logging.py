"""AI usage logging — records token usage and estimated cost to PostgreSQL.

This module is intentionally fire-and-forget: logging failures are caught
and logged but never propagate to the caller. AI features should never
break because of usage tracking issues.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.db import AiUsageLog

logger = structlog.get_logger(__name__)


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_price_per_mtok: float,
    output_price_per_mtok: float,
) -> Decimal:
    """Estimate USD cost from token counts and per-million-token pricing.

    Returns a Decimal with 6 decimal places.
    """
    input_cost = (
        Decimal(str(input_tokens))
        / Decimal("1000000")
        * Decimal(str(input_price_per_mtok))
    )
    output_cost = (
        Decimal(str(output_tokens))
        / Decimal("1000000")
        * Decimal(str(output_price_per_mtok))
    )
    total = input_cost + output_cost
    return total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def log_ai_usage(
    project_id: str,
    user_id: str | None,
    source: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    session: AsyncSession | None = None,
) -> None:
    """Record an AI usage entry to the database.

    Estimates cost using configured pricing. Silently catches and logs
    any errors — usage tracking must never break AI features.

    Args:
        project_id: The project this usage belongs to.
        user_id: Optional user who triggered the AI call.
        source: Source label — 'chat', 'summary', 'mcp', or 'pr_analysis'.
        model: Model identifier (e.g. 'us.anthropic.claude-sonnet-4-6').
        input_tokens: Number of input/prompt tokens consumed.
        output_tokens: Number of output/completion tokens produced.
        session: Optional AsyncSession for testing. When not provided,
            a background session is created via get_background_session().
    """
    try:
        settings = get_settings()
        cost = estimate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price_per_mtok=settings.ai_cost_input_per_mtok,
            output_price_per_mtok=settings.ai_cost_output_per_mtok,
        )

        entry = AiUsageLog(
            project_id=project_id,
            user_id=user_id,
            source=source,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
        )

        if session is not None:
            # Use the provided session (test injection or caller's transaction)
            session.add(entry)
            await session.commit()
        else:
            # Use a separate background session to avoid interfering with the
            # caller's transaction
            from app.services.postgres import get_background_session

            async with get_background_session() as usage_session:
                usage_session.add(entry)
                await usage_session.commit()

        logger.info(
            "ai_usage_logged",
            project_id=project_id,
            source=source,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=str(cost),
        )
    except Exception as exc:
        logger.warning(
            "ai_usage_logging_failed",
            error=str(exc),
            project_id=project_id,
            source=source,
        )
