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
            r"(?is)\bignore\b.{0,20}\b(?:previous|all)?\s*instructions\b",
            r"(?is)\bforget\b.{0,20}\b(?:previous|all)?\s*instructions\b",
            r"(?is)\bsystem\s*prompt\b",
            r"(?is)\bdisregard\b.{0,20}\b(?:previous|all)?\s*instructions\b",
            r"(?is)\byou\s*are\s*now\b",
            r"(?is)\bact\s*as\b",
            r"(?is)\bfrom\s*now\s*on\b",
            r"(?is)\bprint\b.{0,20}\b(?:instructions|prompt)\b",
            r"(?is)new\s*rules",
            r"(?is)new\s*instructions",
            # Ukrainian patterns
            r"(?is)(?:ігноруй|проігноруй|забудь|відкинь).{0,20}(?:всі|попередні)?\s*(?:інструкції|вказівки|правила)",
            r"(?is)системний\s*промпт",
            r"(?is)поводься\s*як",
            r"(?is)дій\s*як",
            r"(?is)відтепер\s*ти",
            r"(?is)нові\s*правила",
            r"(?is)нові\s*інструкції",
            r"(?is)виведи.{0,20}(?:інструкції|промпт|правила)",
            # Russian patterns
            r"(?is)(?:игнорируй|проигнорируй|забудь|отбрось).{0,20}(?:все|предыдущие)?\s*(?:инструкции|указания|правила)",
            r"(?is)системный\s*промпт",
            r"(?is)веди\s*себя\s*как",
            r"(?is)действуй\s*как",
            r"(?is)отныне\s*ты",
            r"(?is)новые\s*правила",
            r"(?is)новые\s*инструкции",
            r"(?is)выведи.{0,20}(?:инструкции|промпт|правила)",
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
