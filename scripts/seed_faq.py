import asyncio
import sys
from pathlib import Path

# Додаємо корінь проєкту в PYTHONPATH для коректних імпортів
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.services.openai_service import OpenAIService
from app.services.vector_service import VectorService

FAQ_DATA = [
    {
        "category": "Доставка та терміни",
        "text": "Товари в наявності: Відправка здійснюється протягом 3–5 робочих днів після підтвердження замовлення. ТТН надсилається в СМС/месенджер після передачі посилці логістичній компанії.",
    },
    {
        "category": "Доставка та терміни",
        "text": "Товари 'Під замовлення': Товар везеться від європейського постачальника під замовлення. Орієнтовний термін доставки в Україну становить від 14 до 20 календарних днів.",
    },
    {
        "category": "Доставка та терміни",
        "text": "Служби доставки: Відправляємо по всій Україні через Нову Пошту (відділення, поштомат, кур'єр). Доставка Укрпоштою відсутня. Самовивіз наразі відсутній, працюємо тільки на доставку.",
    },
    {
        "category": "Способи оплати",
        "text": "Оплата при отриманні: Можлива післяплата (накладений платіж) у відділенні Нової Пошти. Комісія Нової Пошти: 2% від суми + 20 грн.",
    },
    {
        "category": "Способи оплати",
        "text": "Передоплата: Для товарів 'Під замовлення' (доставка 14-20 днів) потрібна часткова передоплата 10% як гарантія. Решта оплачується при отриманні.",
    },
    {
        "category": "Способи оплати",
        "text": "Безготівковий розрахунок: Оплата можлива на рахунок ФОП 2/3 групи (IBAN). Працюємо без ПДВ. Реквізити надає менеджер після оформлення замовлення.",
    },
    {
        "category": "Стан та якість",
        "text": "Стан товару: Магазин Digital Dreams продає виключно нову, 100% оригінальну техніку у заводському пакуванні із цілісними пломбами виробника. Ми не продаємо вживані, відновлені (Refurbished) чи копії.",
    },
    {
        "category": "Стан та якість",
        "text": "Комплектація: Повністю відповідає офіційному заводському постачанню. Точний перелік вказано в характеристиках на сайті.",
    },
    {
        "category": "Гарантія",
        "text": "Гарантія: На всю техніку надається гарантія 12 місяців від нашого магазину Digital Dreams. Обслуговування через наш сервісний центр. Видається гарантійний талон з печаткою.",
    },
    {
        "category": "Повернення та обмін",
        "text": "Повернення 14 днів: Можливе, якщо збережено товарний вигляд, заводські пломби не зірвані, пристрій не вмикався і не має слідів використання. Розпакований товар належної якості зірваними пломбами поверненню не підлягає.",
    },
    {
        "category": "Повернення та обмін",
        "text": "Заводський брак: Якщо виявлено дефект, товар направляється в сервісний центр на експертизу. Після підтвердження браку здійснюється ремонт, заміна або повернення коштів.",
    },
    {
        "category": "Опт",
        "text": "Оптові замовлення: Якщо потрібна кількість перевищує залишок, товар замовляється з Європи (14-20 днів). Індивідуальна ціна обговорюється з менеджером.",
    },
]


async def main():
    settings = get_settings()
    openai_service = OpenAIService(settings)
    vector_service = VectorService(settings)

    print("Generating embeddings for FAQ...")
    texts = [item["text"] for item in FAQ_DATA]
    embeddings = await openai_service.generate_embeddings_batch(texts)

    vectors: list[tuple[str, list[float], dict[str, str]]] = []
    for i, (item, emb) in enumerate(zip(FAQ_DATA, embeddings, strict=True)):
        vector_id = f"faq_rule_{i}"
        metadata = {
            "source": "store_policy",
            "category": str(item["category"]),
            "text": str(item["text"]),
        }
        vectors.append((vector_id, emb, metadata))

    print(f"Upserting {len(vectors)} rules to Pinecone...")
    await vector_service.upsert_vectors(vectors)
    print("Base FAQ successfully seeded into Vector Database.")


if __name__ == "__main__":
    asyncio.run(main())
