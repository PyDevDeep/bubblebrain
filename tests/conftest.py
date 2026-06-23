import os
from unittest.mock import Mock

os.environ["OPENAI_API_KEY"] = "sk-fake-key"
os.environ["PINECONE_API_KEY"] = "fake-key"
os.environ["PINECONE_ENVIRONMENT"] = "fake-env"
os.environ["API_KEY_SECRET"] = "fake-secret"
os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
os.environ["TELEGRAM_CHAT_ID"] = "123"
os.environ["WOO_CK"] = "ck"
os.environ["WOO_CS"] = "cs"

import pytest

from app.core.config import Settings


@pytest.fixture
def mock_settings(tmp_path):
    settings = Mock(spec=Settings)

    # Cache
    db_file = tmp_path / "test_cache.db"
    settings.cache_db_path = str(db_file)
    settings.cache_ttl_days = 7

    # Telegram
    settings.telegram_bot_token = "fake_token"
    settings.telegram_chat_id = "12345"
    settings.telegram_topic_general = None
    settings.telegram_topic_leads = None
    settings.telegram_topic_hot_leads = None
    settings.telegram_topic_conversions = None
    settings.telegram_topic_bot_stats = None
    settings.telegram_topic_prices = None
    settings.telegram_topic_errors = None
    settings.telegram_contact_url = "http://tg"
    settings.viber_contact_url = "http://vb"

    mock_secret_openai = Mock()
    mock_secret_openai.get_secret_value.return_value = "fake-openai-key"
    settings.openai_api_key = mock_secret_openai
    settings.embedding_model = "text-embedding-ada-002"
    settings.openai_model = "gpt-4"
    settings.max_tokens_response = 1000
    settings.model_pricing = {"gpt-4": (5.0, 15.0), "text-embedding-ada-002": (0.0, 0.0)}

    # Pinecone
    mock_secret_pinecone = Mock()
    mock_secret_pinecone.get_secret_value.return_value = "fake-pinecone-key"
    settings.pinecone_api_key = mock_secret_pinecone
    settings.pinecone_environment = "test-env"
    settings.pinecone_index_name = "test-index"
    settings.pinecone_dimension = 1536
    settings.pinecone_metric = "cosine"

    # Scraper
    settings.euro_rate = 40.0

    # Woo
    settings.woo_ck = "ck"
    settings.woo_cs = "cs"
    settings.woo_url = "https://mock-woo.com"
    settings.supplier_url = "https://mock-supplier.com"

    return settings
