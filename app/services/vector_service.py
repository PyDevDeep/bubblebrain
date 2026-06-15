import asyncio
from typing import Any, cast

from pinecone import (  # type: ignore[reportMissingTypeStubs]
    Pinecone,
    PineconeException,
    ServerlessSpec,
)

from app.core.config import Settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class VectorService:
    def __init__(self, settings: Settings) -> None:
        """
        Iнiцiалiзацiя Pinecone клiєнта та отримання посилання на iндекс.
        Автоматично перевіряє наявність індексу.
        """
        self.settings = settings
        self.pc = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
        self.index_name = settings.pinecone_index_name.lower()
        self.dimension = 1536
        self.metric = "cosine"

        self.index: Any = self.pc.Index(self.index_name)  # type: ignore[reportUnknownMemberType]

    async def initialize(self) -> None:
        await asyncio.to_thread(self.ensure_index_exists)

    def ensure_index_exists(self) -> None:
        """
        Перевiряє наявнiсть iндексу. Створює при вiдсутностi.
        """
        try:
            active_indexes = [idx.name for idx in self.pc.list_indexes()]

            if self.index_name not in active_indexes:
                logger.info("Creating Pinecone index", index_name=self.index_name)

                spec = ServerlessSpec(cloud="aws", region="us-east-1")

                self.pc.create_index(  # type: ignore[reportUnknownMemberType]
                    name=self.index_name,
                    dimension=self.dimension,
                    metric=self.metric,
                    spec=spec,
                )
                logger.info("Index created", index_name=self.index_name)
            else:
                logger.info("Index exists", index_name=self.index_name)
        except PineconeException as e:  # type: ignore
            logger.error("Failed to ensure Pinecone index exists", error=str(e))  # type: ignore
            raise

    async def upsert_vectors(self, vectors: list[tuple[str, list[float], dict[str, Any]]]) -> int:
        """
        Запис векторiв у Pinecone батчами по 100 для уникнення rate limit.
        """
        batch_size = 100
        total_upserted = 0

        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            formatted_batch: list[dict[str, Any]] = [
                {"id": v_id, "values": v_emb, "metadata": v_meta} for v_id, v_emb, v_meta in batch
            ]

            try:
                await asyncio.to_thread(self.index.upsert, vectors=formatted_batch)
                total_upserted += len(batch)
                logger.info(
                    "Upserted batch",
                    current_batch_size=len(batch),
                    total_upserted=total_upserted,
                    total_vectors=len(vectors),
                )

                if i + batch_size < len(vectors):
                    await asyncio.sleep(0.5)
            except PineconeException as e:  # type: ignore
                logger.error("Failed to upsert vectors in Pinecone", error=str(e))  # type: ignore
                raise

        return total_upserted

    def query_similar(
        self, query_vector: list[float], top_k: int, score_threshold: float
    ) -> list[dict[str, Any]]:
        """
        Пошук найбiльш схожих векторiв. Відсіювання результатів нижче score_threshold.
        """
        try:
            response = self.index.query(
                vector=query_vector,
                top_k=top_k,
                include_metadata=True,
                include_values=False,
            )

            results: list[dict[str, Any]] = []
            matches = cast(list[Any], response.matches)

            for match in matches:
                score = float(match.score)
                if score >= score_threshold:
                    results.append(
                        {
                            "id": str(match.id),
                            "score": score,
                            "metadata": match.metadata,
                        }
                    )
            return results
        except PineconeException as e:  # type: ignore
            logger.error("Failed to query similar vectors in Pinecone", error=str(e))  # type: ignore
            raise

    def delete_by_source(self, source: str) -> None:
        """
        Видалення всiх векторiв за metadata filter: source == source.
        """
        try:
            self.index.delete(filter={"source": source})
            logger.info("Deleted vectors by source", source=source)
        except PineconeException as e:  # type: ignore
            logger.error("Failed to delete vectors by source in Pinecone", error=str(e))  # type: ignore
            raise
