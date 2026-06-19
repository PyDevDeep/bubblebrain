from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Request

from app.core.security import verify_api_key


@pytest.mark.asyncio
async def test_verify_api_key_valid(mock_settings):
    request = Mock(spec=Request)
    request.client.host = "127.0.0.1"

    mock_secret = Mock()
    mock_secret.get_secret_value.return_value = "fake-secret"
    mock_settings.api_key_secret = mock_secret

    res = await verify_api_key(request, "fake-secret", mock_settings)
    assert res == "fake-secret"


@pytest.mark.asyncio
async def test_verify_api_key_missing(mock_settings):
    request = Mock(spec=Request)
    request.client.host = "127.0.0.1"
    request.url.path = "/api/v1/test"

    with pytest.raises(HTTPException) as exc:
        await verify_api_key(request, None, mock_settings)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing API Key"


@pytest.mark.asyncio
async def test_verify_api_key_invalid(mock_settings):
    request = Mock(spec=Request)
    request.client.host = "127.0.0.1"
    request.url.path = "/api/v1/test"

    mock_secret = Mock()
    mock_secret.get_secret_value.return_value = "fake-secret"
    mock_settings.api_key_secret = mock_secret

    with pytest.raises(HTTPException) as exc:
        await verify_api_key(request, "wrong-key", mock_settings)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Invalid API Key"
