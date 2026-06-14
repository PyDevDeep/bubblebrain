"""
Сервіс для забезпечення базового захисту від Prompt Injection (Guardrails).
"""

import re

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
        self.injection_patterns = [
            # English patterns
            r"(?i)\bignore\b.*\b(?:previous|all)?\s*instructions\b",
            r"(?i)\bforget\b.*\b(?:previous|all)?\s*instructions\b",
            r"(?i)\bsystem\s*prompt\b",
            r"(?i)\bdisregard\b.*\b(?:previous|all)?\s*instructions\b",
            r"(?i)\byou\s*are\s*now\b",
            r"(?i)\bact\s*as\b",
            r"(?i)\bfrom\s*now\s*on\b",
            r"(?i)\bprint\b.*\b(?:instructions|prompt)\b",
            r"(?i)new\s*rules",
            r"(?i)new\s*instructions",
            # Ukrainian patterns
            r"(?i)(?:ігноруй|проігноруй|забудь|відкинь).*(?:всі|попередні)?\s*(?:інструкції|вказівки|правила)",
            r"(?i)системний\s*промпт",
            r"(?i)поводься\s*як",
            r"(?i)дій\s*як",
            r"(?i)відтепер\s*ти",
            r"(?i)нові\s*правила",
            r"(?i)нові\s*інструкції",
            r"(?i)виведи.*(?:інструкції|промпт|правила)",
            # Russian patterns
            r"(?i)(?:игнорируй|проигнорируй|забудь|отбрось).*(?:все|предыдущие)?\s*(?:инструкции|указания|правила)",
            r"(?i)системный\s*промпт",
            r"(?i)веди\s*себя\s*как",
            r"(?i)действуй\s*как",
            r"(?i)отныне\s*ты",
            r"(?i)новые\s*правила",
            r"(?i)новые\s*инструкции",
            r"(?i)выведи.*(?:инструкции|промпт|правила)",
        ]

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
