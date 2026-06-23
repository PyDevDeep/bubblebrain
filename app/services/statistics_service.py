import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.constants import STATISTICS_TEMPLATE
from app.core.db import AsyncSessionLocal
from app.models.chat_memory import ChatMessage
from app.services.telegram_service import TelegramService
from app.services.woo_service import WooService

logger = logging.getLogger(__name__)


async def fetch_prometheus_data(settings: Settings) -> dict[str, float]:
    """Collects aggregated metrics for the last 24 hours from local Prometheus."""
    metrics = {
        "tokens": 0.0,
        "latency_avg": 0.0,
        "errors": 0.0,
        "price_alerts": 0.0,
        "leads_contact": 0.0,
        "leads_hot": 0.0,
        "conversions": 0.0,
    }

    # Prometheus HTTP API URL
    prom_url = getattr(settings, "prometheus_url", "http://prometheus:9090/api/v1/query")

    queries = {
        "tokens": "sum(increase(llm_tokens_total[24h]))",
        "latency_avg": "rate(llm_latency_seconds_sum[24h]) / rate(llm_latency_seconds_count[24h])",
        "errors": 'sum(increase(llm_requests_total{status="error"}[24h])) + sum(increase(bot_messages_total{status="error"}[24h]))',
        "price_alerts": "sum(increase(price_alerts_total[24h]))",
        "leads_contact": 'sum(increase(leads_created_total{type="contact"}[24h]))',
        "leads_hot": 'sum(increase(leads_created_total{type="checkout"}[24h]))',
        "conversions": 'sum(increase(leads_created_total{type="conversion"}[24h]))',
    }

    async def _fetch_metric(client: httpx.AsyncClient, key: str, query: str) -> None:
        try:
            resp = await client.get(prom_url, params={"query": query})
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("data", {}).get("result", [])
                if results:
                    val_str = results[0].get("value", [0, "0"])[1]
                    if val_str and val_str != "NaN":
                        metrics[key] = float(val_str)
        except Exception:
            logger.error(f"Failed to fetch prometheus metric {key}", exc_info=True)

    async with httpx.AsyncClient(timeout=10.0) as client:
        await asyncio.gather(*(_fetch_metric(client, k, q) for k, q in queries.items()))

    return metrics


async def fetch_unique_users_24h() -> int:
    """Number of unique users (sessions) in the last 24 hours."""
    past_24h = datetime.now(UTC) - timedelta(hours=24)
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(func.count(func.distinct(ChatMessage.session_id))).where(
                ChatMessage.created_at >= past_24h
            )
            result = await session.execute(stmt)
            return result.scalar() or 0
        except Exception:
            logger.error("Failed to fetch unique users", exc_info=True)
            return 0


async def gather_and_send_daily_report_job() -> None:
    """Function for APScheduler that aggregates data and sends it to Telegram."""
    settings = get_settings()

    telegram_service = TelegramService(settings)
    woo_service = WooService(settings)

    # 1. Prometheus Metrics
    prom_task = asyncio.create_task(fetch_prometheus_data(settings))

    # 2. SQLite (Unique users)
    users_task = asyncio.create_task(fetch_unique_users_24h())

    # 3. WooCommerce
    woo_task = asyncio.create_task(woo_service.get_daily_orders_stats())

    prom_stats, unique_users, woo_stats = await asyncio.gather(prom_task, users_task, woo_task)

    # Message formatting
    date_str = datetime.now(UTC).strftime("%d.%m.%Y")

    msg_lines = [
        line.format(
            date_str=date_str,
            unique_users=unique_users,
            tokens=int(prom_stats["tokens"]),
            latency_avg=prom_stats["latency_avg"],
            errors=int(prom_stats["errors"]),
            price_alerts=int(prom_stats["price_alerts"]),
            leads_contact=int(prom_stats["leads_contact"]),
            leads_hot=int(prom_stats["leads_hot"]),
            conversions=int(prom_stats["conversions"]),
            woo_total=woo_stats.get("total", 0),
            woo_processing=woo_stats.get("processing", 0),
            woo_on_hold=woo_stats.get("on-hold", 0),
            woo_paid=woo_stats.get("paid", 0),
        )
        for line in STATISTICS_TEMPLATE
    ]

    # Tags
    tags = woo_stats.get("tags", {})
    if tags:
        msg_lines.append("")
        msg_lines.append("🏷 <b>Джерела / Мітки (від усього):</b>")
        total_orders = woo_stats.get("total", 1) or 1

        # Sort tags by count descending
        sorted_tags = sorted(tags.items(), key=lambda item: item[1], reverse=True)

        for tag, count in sorted_tags:
            pct = (count / total_orders) * 100
            msg_lines.append(f"   - {tag}: {count} ({pct:.1f}%)")

    message = "\n".join(msg_lines)

    # Send to 'stat' topic
    try:
        await telegram_service.send_alert(message, alert_type="stat")
        logger.info("Daily statistics report sent.")
    finally:
        await woo_service.close()
