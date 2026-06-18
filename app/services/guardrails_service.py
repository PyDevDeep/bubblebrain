"""
Сервіс для забезпечення базового захисту від Prompt Injection (Guardrails).
"""

import re

from app.core.constants import INJECTION_PATTERNS
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class GuardrailsService:
    """
    Клас, що відповідає за валідацію користувацького вводу
    на наявність спроб обходу системних інструкцій.
    """

    def __init__(self) -> None:
        """
        Ініціалізує сервіс, завантажуючи та компілюючи регулярні вирази
        для виявлення атак англійською, українською та російською мовами.
        """
        # Регулярні вирази та патерни для виявлення спроб Prompt Injection (Англійська + Українська + Російська)
        self.injection_patterns = INJECTION_PATTERNS

        self.compiled_patterns = [re.compile(p) for p in self.injection_patterns]

    def validate_input(self, text: str, client_ip: str | None = None) -> bool:
        """
        Перевіряє ввід на наявність патернів Prompt Injection.
        Повертає True, якщо ввід безпечний, і False, якщо знайдена спроба ін'єкції.
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
