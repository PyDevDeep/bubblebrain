from datetime import UTC, datetime

from pydantic import BaseModel


class CacheEntry(BaseModel):
    sku: str
    product_name: str
    price_eur: float
    price_uah: float
    availability_status: str
    delivery_time_description: str
    updated_at: datetime

    def is_expired(self, ttl_days: int) -> bool:
        now = datetime.now(UTC)
        updated = self.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return (now - updated).days >= ttl_days
