from collections.abc import Sequence

from openai import AsyncOpenAI, OpenAIError, RateLimitError

from app.core.config import Settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        """
        Iнiцiалiзацiя AsyncOpenAI клiєнта.
        Збереження моделей для embeddigns та chat completions з конфігурації.
        """
        self.client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        self.embedding_model = settings.embedding_model
        self.openai_model = settings.openai_model

    async def generate_embedding(self, text: str) -> list[float]:
        """
        Генерацiя вектора розмiрнiстю 1536 для одного текстового фрагмента.
        """
        if not text or not text.strip():
            raise ValueError("Input text for embedding cannot be empty")

        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except RateLimitError as e:
            logger.warning("OpenAI RateLimitError during embedding generation", error=str(e))
            raise e
        except OpenAIError as e:
            logger.error("OpenAI APIError during embedding generation", error=str(e))
            raise e

    async def generate_embeddings_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Батч-генерацiя embeddings для кiлькох текстiв за один API-виклик.
        """
        if not texts:
            raise ValueError("Input texts list for batch embedding cannot be empty")

        # Перевірка на наявність порожніх рядків у батчі, щоб уникнути падіння всього запиту
        clean_texts = [text if text.strip() else " " for text in texts]

        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=clean_texts,
            )
            # Гарантуємо збереження порядку повернених векторів відносно вхідного списку
            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in sorted_data]
        except RateLimitError as e:
            logger.warning("OpenAI RateLimitError during batch embedding", error=str(e))
            raise e
        except OpenAIError as e:
            logger.error("OpenAI APIError during batch embedding", error=str(e))
            raise e
