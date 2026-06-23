import time
from collections.abc import AsyncGenerator, Sequence
from typing import cast

from openai import AsyncOpenAI, AsyncStream, OpenAIError, RateLimitError
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.core.metrics import (
    llm_cost_usd_total,
    llm_latency_seconds,
    llm_requests_total,
    llm_tokens_total,
    llm_ttft_seconds,
)

logger = get_logger(__name__)

logger = get_logger(__name__)


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        """
        Initialize the AsyncOpenAI client.
        Store models and limits from the configuration.
        """
        self.client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        self.embedding_model = settings.embedding_model
        self.openai_model = settings.openai_model
        self.max_tokens_response = settings.max_tokens_response
        self.model_pricing = settings.model_pricing

    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        prices = self.model_pricing.get(model, (0.0, 0.0))
        return (prompt_tokens * prices[0] / 1000000) + (completion_tokens * prices[1] / 1000000)

    def _record_metrics(self, model: str, prompt_tokens: int, completion_tokens: int = 0) -> None:
        llm_tokens_total.labels(model=model, token_type="prompt").inc(prompt_tokens)  # noqa: S106
        if completion_tokens > 0:
            llm_tokens_total.labels(model=model, token_type="completion").inc(completion_tokens)  # noqa: S106
        cost = self._calculate_cost(model, prompt_tokens, completion_tokens)
        if cost > 0:
            llm_cost_usd_total.labels(model=model).inc(cost)

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((RateLimitError, OpenAIError)),
    )
    async def generate_embedding(self, text: str) -> list[float]:
        """
        Generate a vector of dimension 1536 for a single text fragment.
        """
        if not text or not text.strip():
            raise ValueError("Input text for embedding cannot be empty")

        try:
            with llm_latency_seconds.labels(model=self.embedding_model).time():
                response = await self.client.embeddings.create(
                    model=self.embedding_model,
                    input=text,
                )

            llm_requests_total.labels(model=self.embedding_model, status="success").inc()

            if response.usage:
                self._record_metrics(self.embedding_model, response.usage.prompt_tokens, 0)

            return response.data[0].embedding
        except RateLimitError:
            llm_requests_total.labels(model=self.embedding_model, status="rate_limit").inc()
            logger.warning("OpenAI RateLimitError during embedding generation", exc_info=True)
            raise
        except OpenAIError:
            llm_requests_total.labels(model=self.embedding_model, status="error").inc()
            logger.error("OpenAI APIError during embedding generation", exc_info=True)
            raise

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((RateLimitError, OpenAIError)),
    )
    async def generate_embeddings_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Batch generation of embeddings for multiple texts in a single API call.
        """
        if not texts:
            raise ValueError("Input texts list for batch embedding cannot be empty")

        clean_texts = [text if text.strip() else " " for text in texts]

        try:
            with llm_latency_seconds.labels(model=self.embedding_model).time():
                response = await self.client.embeddings.create(
                    model=self.embedding_model,
                    input=clean_texts,
                )

            llm_requests_total.labels(model=self.embedding_model, status="success").inc()

            if response.usage:
                self._record_metrics(self.embedding_model, response.usage.prompt_tokens, 0)

            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in sorted_data]
        except RateLimitError:
            llm_requests_total.labels(model=self.embedding_model, status="rate_limit").inc()
            logger.warning("OpenAI RateLimitError during batch embedding", exc_info=True)
            raise
        except OpenAIError:
            llm_requests_total.labels(model=self.embedding_model, status="error").inc()
            logger.error("OpenAI APIError during batch embedding", exc_info=True)
            raise

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
        Generate a text response with RAG context.
        """
        context_text = "\n\n".join(context_chunks)

        if "{context}" in system_prompt:
            formatted_system_prompt = system_prompt.replace("{context}", context_text)
        else:
            formatted_system_prompt = f"{system_prompt}\n\nContext:\n{context_text}"

        messages = [
            {"role": "system", "content": formatted_system_prompt},
            {"role": "user", "content": user_message},
        ]

        kwargs = {}
        if response_format:
            kwargs["response_format"] = response_format

        try:
            with llm_latency_seconds.labels(model=self.openai_model).time():
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

            llm_requests_total.labels(model=self.openai_model, status="success").inc()

            if response.usage:
                self._record_metrics(
                    self.openai_model,
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )

            content = response.choices[0].message.content
            return content if content else ""
        except RateLimitError:
            llm_requests_total.labels(model=self.openai_model, status="rate_limit").inc()
            logger.warning("OpenAI RateLimitError during chat completion", exc_info=True)
            raise
        except OpenAIError:
            llm_requests_total.labels(model=self.openai_model, status="error").inc()
            logger.error("OpenAI APIError during chat completion", exc_info=True)
            raise

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((RateLimitError, OpenAIError)),
    )
    async def stream_chat_completion(
        self, system_prompt: str, user_message: str, context_chunks: list[str]
    ) -> AsyncGenerator[str]:
        """
        Streaming version of chat completion (SSE).
        Returns a token generator.
        """
        context_text = "\n\n".join(context_chunks)

        if "{context}" in system_prompt:
            formatted_system_prompt = system_prompt.replace("{context}", context_text)
        else:
            formatted_system_prompt = f"{system_prompt}\n\nContext:\n{context_text}"

        messages = [
            {"role": "system", "content": formatted_system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            llm_requests_total.labels(model=self.openai_model, status="success").inc()

            start_time = time.time()
            first_token_received = False

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
                if not first_token_received:
                    ttft = time.time() - start_time
                    llm_ttft_seconds.labels(model=self.openai_model).observe(ttft)
                    first_token_received = True

                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except RateLimitError:
            llm_requests_total.labels(model=self.openai_model, status="rate_limit").inc()
            logger.warning("OpenAI RateLimitError during stream chat completion", exc_info=True)
            raise
        except OpenAIError:
            llm_requests_total.labels(model=self.openai_model, status="error").inc()
            logger.error("OpenAI APIError during stream chat completion", exc_info=True)
            raise
