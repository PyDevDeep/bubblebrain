from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_client_ip(request: Request) -> str:
    """
    Витягування IP клієнта.
    Пріоритет віддається заголовку X-Forwarded-For від Nginx.
    """
    if "x-forwarded-for" in request.headers:
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=get_client_ip)
