import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.services.openai_service import OpenAIService
from app.services.vector_service import VectorService

FAQ_PATH = Path(__file__).resolve().parent.parent / "data" / "faq_data.json"


async def main():
    settings = get_settings()
    openai_service = OpenAIService(settings)
    vector_service = VectorService(settings)
    await vector_service.initialize()

    with open(FAQ_PATH, encoding="utf-8") as f:  # noqa: ASYNC230
        faq_data = json.load(f)

    print("Generating embeddings for FAQ...")
    texts_to_embed = [
        f"Питання: {item['questions']}\nВідповідь: {item['answer']}" for item in faq_data
    ]

    embeddings = await openai_service.generate_embeddings_batch(texts_to_embed)

    vectors: list[tuple[str, list[float], dict[str, str]]] = []
    for i, (item, emb) in enumerate(zip(faq_data, embeddings, strict=True)):
        vector_id = f"faq_rule_{i}"
        metadata = {
            "source": "store_policy",
            "category": item["category"],
            "questions": item["questions"],
            "answer": item["answer"],
        }
        if "topic" in item:
            metadata["topic"] = item["topic"]
        vectors.append((vector_id, emb, metadata))

    print(f"Upserting {len(vectors)} rules to Pinecone...")

    try:
        await vector_service.delete_by_source("store_policy")
        print("Old store policies deleted.")
    except Exception as e:
        print(f"No old policies to delete or error occurred: {e}")

    await vector_service.upsert_vectors(vectors)
    print("Base FAQ successfully seeded into Vector Database.")

    await openai_service.client.close()


if __name__ == "__main__":
    asyncio.run(main())
