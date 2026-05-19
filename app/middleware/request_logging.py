import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        bound_logger = logger.bind(request_id=request_id)
        method = scope.get("method", "")
        path = scope.get("path", "")

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                headers = MutableHeaders(scope=message)
                headers.append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            bound_logger.exception("Request failed", method=method, path=path)
            raise exc
        finally:
            process_time = time.perf_counter() - start_time
            bound_logger.info(
                "Request completed",
                method=method,
                path=path,
                status_code=status_code,
                latency=round(process_time, 4),
            )
