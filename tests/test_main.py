from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_debug_fs(async_client):
    response = await async_client.get("/debug-fs")
    assert response.status_code == 200
    data = response.json()
    assert "exists" in data
    assert "files" in data
    assert "path" in data


def test_create_application():
    from app.main import create_application

    app = create_application()
    assert isinstance(app, FastAPI)
    assert app.title == "Chatbot AI Backend"

    # Check if static is mounted
    assert any(getattr(route, "name", None) == "frontend" for route in app.routes)

    # Check if debug-fs works
    client = TestClient(app)
    response = client.get("/debug-fs")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("app.core.db.init_db", new_callable=AsyncMock)
@patch("app.services.cache_service.CacheService")
@patch("app.services.vector_service.VectorService")
@patch("app.main.AsyncIOScheduler")
@patch("apscheduler.jobstores.sqlalchemy.SQLAlchemyJobStore")
@patch("app.api.dependencies.get_scraper_service")
@patch("app.api.dependencies.get_woo_service")
@patch("app.main.sentry_sdk")
@patch("app.main.get_settings")
async def test_lifespan(
    mock_get_settings,
    mock_sentry,
    mock_get_woo_service,
    mock_get_scraper,
    mock_jobstore,
    mock_scheduler,
    mock_vector_service,
    mock_cache_service,
    mock_init_db,
):
    from app.main import lifespan

    # Arrange
    mock_settings = MagicMock()
    mock_settings.sentry_dsn = "http://test@localhost/1"
    mock_settings.pinecone_environment = "test-env"
    mock_settings.log_level = "INFO"
    mock_get_settings.return_value = mock_settings

    mock_cache_instance = AsyncMock()
    mock_cache_service.return_value = mock_cache_instance

    mock_vector_instance = AsyncMock()
    mock_vector_service.return_value = mock_vector_instance

    mock_sched_instance = MagicMock()
    mock_scheduler.return_value = mock_sched_instance

    mock_scraper = AsyncMock()
    mock_get_scraper.return_value = mock_scraper

    mock_woo_service = AsyncMock()
    mock_get_woo_service.return_value = mock_woo_service

    app = FastAPI()

    # Act
    with patch.dict("os.environ", {"RUN_CRON": "true"}):
        async with lifespan(app):
            # Assert startup
            mock_init_db.assert_awaited_once()
            mock_cache_instance.initialize.assert_awaited_once()
            mock_sentry.init.assert_called_once()
            mock_vector_instance.initialize.assert_awaited_once()
            mock_sched_instance.add_job.assert_called()
            mock_sched_instance.start.assert_called_once()

    # Assert shutdown
    mock_sched_instance.shutdown.assert_called_once_with(wait=False)
    mock_scraper.close.assert_awaited_once()
    mock_woo_service.close.assert_awaited_once()
    mock_sentry.flush.assert_called_once()
