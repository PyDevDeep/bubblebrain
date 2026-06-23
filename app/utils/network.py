from fastapi import Request
from slowapi.util import get_remote_address


def get_client_ip(request: Request) -> str:
    """
    Safely extract client IP behind Nginx.
    Prioritizes X-Forwarded-For and X-Real-IP headers.
    Falls back to request.client.host or slowapi fallback.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host
    return get_remote_address(request)
