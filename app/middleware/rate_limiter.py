from slowapi import Limiter

from app.utils.network import get_client_ip

# TODO(TechDebt): Configure Limiter to use Redis as a storage backend for production
# to ensure rate limits are synced across multiple workers/instances.
limiter = Limiter(key_func=get_client_ip)
