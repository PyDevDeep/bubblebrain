import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# auto_error=False allows us to manually handle the absence of the header and return 401 instead of 403
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    FastAPI Dependency for validating the API key from the X-API-Key header.
    Protects endpoints from unauthorized access.
    """
    client_ip = request.client.host if request.client else "unknown"

    if not api_key:
        logger.warning(
            "Authentication failed: Missing API Key",
            client_ip=client_ip,
            path=request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key",
        )

    # Use timing-safe comparison to prevent timing attacks for key guessing
    is_valid = secrets.compare_digest(api_key, settings.api_key_secret.get_secret_value())

    if not is_valid:
        logger.warning(
            "Authentication failed: Invalid API Key",
            client_ip=client_ip,
            path=request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    return api_key
