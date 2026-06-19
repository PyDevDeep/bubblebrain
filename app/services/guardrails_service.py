"""
Service for providing basic protection against Prompt Injection (Guardrails).
"""

import re

from app.core.constants import INJECTION_PATTERNS, MAX_PAYLOAD_SIZE
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class GuardrailsService:
    """
    Class responsible for validating user input
    for attempts to bypass system instructions.
    """

    _COMPILED_PATTERN = re.compile(
        "|".join(p.replace("(?is)", "") for p in INJECTION_PATTERNS),
        flags=re.IGNORECASE | re.DOTALL,
    )

    def validate_input(self, text: str, client_ip: str | None = None) -> bool:
        """
        Checks input for Prompt Injection patterns.
        Returns True if the input is safe, and False if an injection attempt is found.
        """
        if not text:
            return True

        if len(text) > MAX_PAYLOAD_SIZE:
            logger.warning(
                "Payload size exceeded limits",
                client_ip=client_ip,
                length=len(text),
            )
            return False

        if self._COMPILED_PATTERN.search(text):
            safe_log_text = text[:500] + ("..." if len(text) > 500 else "")
            logger.warning(
                "Prompt Injection detected by heuristic",
                client_ip=client_ip,
                malicious_input=safe_log_text,
            )
            return False

        return True
