from fastapi import Request
from slowapi.util import get_remote_address


def get_client_ip(request: Request) -> str:
    """
    Safely extract client IP.
    Relies on request.client.host, which is correctly populated
    if uvicorn is running with --proxy-headers and --forwarded-allow-ips.
    If not, we use slowapi fallback.
    """
    if request.client and request.client.host:
        return request.client.host
    return get_remote_address(request)
