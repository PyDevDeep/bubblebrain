"""
Service for providing basic protection against Prompt Injection (Guardrails).
"""

import re

from app.core.constants import INJECTION_PATTERNS
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class GuardrailsService:
    """
    Class responsible for validating user input
    for attempts to bypass system instructions.
    """

    def __init__(self) -> None:
        """
        Initializes the service by loading and compiling regular expressions
        for detecting attacks in English, Ukrainian, and Russian.
        """
        # Regular expressions and patterns for detecting Prompt Injection attempts (English + Ukrainian + Russian)
        self.injection_patterns = INJECTION_PATTERNS

        self.compiled_patterns = [re.compile(p) for p in self.injection_patterns]

    def validate_input(self, text: str, client_ip: str | None = None) -> bool:
        """
        Checks input for Prompt Injection patterns.
        Returns True if the input is safe, and False if an injection attempt is found.
        """
        if not text:
            return True

        for pattern in self.compiled_patterns:
            if pattern.search(text):
                logger.warning(
                    "Prompt Injection detected by heuristic",
                    pattern=pattern.pattern,
                    client_ip=client_ip,
                    malicious_input=text,
                )
                return False

        return True
