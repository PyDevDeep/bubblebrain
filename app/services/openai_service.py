from collections.abc import AsyncGenerator, Sequence
from typing import cast

from openai import AsyncOpenAI, AsyncStream, OpenAIError, RateLimitError
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        """
        Iнiцiалiзацiя AsyncOpenAI клiєнта.
        Збереження моделей та лімітів з конфігурації.
        """
        self.client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        self.embedding_model = settings.embedding_model
        self.openai_model = settings.openai_model
        self.max_tokens_response = settings.max_tokens_response

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((RateLimitError, OpenAIError)),
    )
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

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((RateLimitError, OpenAIError)),
    )
    async def generate_embeddings_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Батч-генерацiя embeddings для кiлькох текстiв за один API-виклик.
        """
        if not texts:
            raise ValueError("Input texts list for batch embedding cannot be empty")

        clean_texts = [text if text.strip() else " " for text in texts]

        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=clean_texts,
            )
            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in sorted_data]
        except RateLimitError as e:
            logger.warning("OpenAI RateLimitError during batch embedding", error=str(e))
            raise e
        except OpenAIError as e:
            logger.error("OpenAI APIError during batch embedding", error=str(e))
            raise e

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((RateLimitError, OpenAIError)),
    )
    async def get_chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        context_chunks: list[str],
        response_format: dict[str, str] | None = None,
    ) -> str:
        """
        Генерацiя текстовоi вiдповiдi з RAG-контекстом.
        """
        context_text = "\n\n".join(context_chunks)

        try:
            # Підставляємо контекст у плейсхолдер {context}
            formatted_system_prompt = system_prompt.format(context=context_text)
        except KeyError:
            # Fallback, якщо промпт не містить плейсхолдера
            formatted_system_prompt = f"{system_prompt}\n\nContext:\n{context_text}"

        messages = [
            {"role": "system", "content": formatted_system_prompt},
            {"role": "user", "content": user_message},
        ]

        kwargs = {}
        if response_format:
            kwargs["response_format"] = response_format

        try:
            response = cast(
                ChatCompletion,
                await self.client.chat.completions.create(
                    model=self.openai_model,
                    messages=messages,  # type: ignore
                    max_tokens=self.max_tokens_response,
                    temperature=0.7,
                    **kwargs,  # type: ignore
                ),
            )
            content = response.choices[0].message.content
            return content if content else ""
        except RateLimitError as e:
            logger.warning("OpenAI RateLimitError during chat completion", error=str(e))
            raise e
        except OpenAIError as e:
            logger.error("OpenAI APIError during chat completion", error=str(e))
            raise e

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((RateLimitError, OpenAIError)),
    )
    async def stream_chat_completion(
        self, system_prompt: str, user_message: str, context_chunks: list[str]
    ) -> AsyncGenerator[str]:
        """
        Streaming-версiя chat completion (SSE).
        Повертає генератор токенів.
        """
        context_text = "\n\n".join(context_chunks)

        try:
            formatted_system_prompt = system_prompt.format(context=context_text)
        except KeyError:
            formatted_system_prompt = f"{system_prompt}\n\nContext:\n{context_text}"

        messages = [
            {"role": "system", "content": formatted_system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            stream = cast(
                AsyncStream[ChatCompletionChunk],
                await self.client.chat.completions.create(
                    model=self.openai_model,
                    messages=messages,  # type: ignore
                    max_tokens=self.max_tokens_response,
                    temperature=0.7,
                    stream=True,
                ),
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except RateLimitError as e:
            logger.warning("OpenAI RateLimitError during stream chat completion", error=str(e))
            raise e
        except OpenAIError as e:
            logger.error("OpenAI APIError during stream chat completion", error=str(e))
            raise e
