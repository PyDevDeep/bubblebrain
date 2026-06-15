from fastapi import Request
from slowapi.util import get_remote_address


def get_client_ip(request: Request) -> str:
    """
    Безпечне витягування IP клієнта.
    Покладається на request.client.host, який коректно заповнюється,
    якщо uvicorn запущено з --proxy-headers та --forwarded-allow-ips.
    Якщо ні, використовуємо фолбек slowapi.
    """
    if request.client and request.client.host:
        return request.client.host
    return get_remote_address(request)
