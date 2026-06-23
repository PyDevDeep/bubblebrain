# 🧠 BubbleBrain

> **AI-powered chatbot backend for e-commerce** — RAG pipeline, price comparison, lead generation, and widget integration in a single production-ready FastAPI service.

[![Python](https://img.shields.io/badge/Python-3.13+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--3.5%2F4-412991?logo=openai&logoColor=white)](https://openai.com/)
[![Pinecone](https://img.shields.io/badge/Pinecone-Vector%20DB-00B5AD)](https://www.pinecone.io/)
[![Poetry](https://img.shields.io/badge/Poetry-dependency%20manager-60A5FA)](https://python-poetry.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Coverage](https://img.shields.io/badge/Coverage-88%25-brightgreen)](https://pytest-cov.readthedocs.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📌 Why BubbleBrain Exists

Modern e-commerce stores lose customers due to slow or absent support. BubbleBrain automates this entirely:

- Answers product questions **instantly** using your store's own data (RAG, no hallucinations)
- **Compares prices** between your store and suppliers in real-time
- **Captures leads** and routes hot prospects directly to Telegram
- Embeds into any frontend via **Chat Widget** — no custom UI required
- Syncs with **WooCommerce** via webhooks to stay up-to-date on orders and inventory

---

## 🚀 Features

- **RAG Engine** — retrieves accurate answers from your product catalog using OpenAI Embeddings + Pinecone vector search
- **Price Comparator** — scrapes supplier sites and compares against WooCommerce prices on demand
- **Lead Pipeline** — classifies intent, captures contact info, and routes hot leads to dedicated Telegram topics
- **Document Ingestion** — uploads and indexes PDF/DOCX files into the vector store via `/api/v1/ingest`
- **WooCommerce Webhook** — receives real-time order/product events and updates internal state
- **Telegram Integration** — broadcasts lead alerts, price updates, bot stats, and errors across topic-organized groups
- **API Key Auth** — static secret key validation on all `/api/v1/*` endpoints
- **Rate Limiting** — 20 requests/min per IP via `slowapi`
- **Structured Logging** — `structlog` + Sentry error tracking
- **Prometheus Metrics** — built-in `/metrics` endpoint, Prometheus container included in Compose
- **Conversation Memory** — per-session chat history stored in SQLite via `aiosqlite`
- **88% Test Coverage** — pytest suite with async support and remote integration tests

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.13 |
| Web Framework | FastAPI + Uvicorn |
| AI / LLM | OpenAI GPT-3.5/4, `text-embedding-3-small` |
| Vector DB | Pinecone |
| Chat Widget |
| WooCommerce | REST API + Webhooks |
| Scheduling | APScheduler |
| HTTP Client | httpx |
| Scraping | BeautifulSoup4, requests |
| Data Validation | Pydantic v2, pydantic-settings |
| Database | SQLite (aiosqlite) + SQLAlchemy |
| Monitoring | Prometheus, Sentry SDK |
| Logging | structlog |
| Rate Limiting | slowapi |
| Containerization | Docker, Docker Compose |
| Dependency Manager | Poetry |
| Linter / Formatter | Ruff |
| Type Checker | mypy (strict), pyright |
| Testing | pytest, pytest-asyncio, pytest-cov |
| Docs | MkDocs Material |

---

## 📦 Quick Start

### Prerequisites

- [ ] Python 3.13+
- [ ] [Poetry](https://python-poetry.org/docs/#installation)
- [ ] Docker + Docker Compose
- [ ] OpenAI API key
- [ ] Pinecone API key (free tier works)

### 1. Clone the repository

```bash
git clone https://github.com/PyDevDeep/BubbleBrain.git
cd BubbleBrain
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```env
# Required
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=pc-...
PINECONE_INDEX_NAME=chatbot-index
API_KEY_SECRET=your_static_secret_key

# WooCommerce (if using webhook integration)
WOO_CK=your_consumer_key
WOO_CS=your_consumer_secret
WOO_URL=https://your-shop-domain.com

# Telegram (for lead alerts)
TELEGRAM_CONTACT_URL=https://t.me/your_bot
```

See [`.env.example`](.env.example) for the full list of available variables.

### 3. Start infrastructure

```bash
docker-compose up -d
```

This launches:
- `bubblebrain-app` on port **8200** (maps to internal 8000)
- `bubblebrain-prometheus` on port **9290**

### 4. Install dependencies and start the dev server

```bash
poetry install
poetry run uvicorn app.main:app --reload
```

API is now available at `http://localhost:8000`.
Interactive Swagger UI: [`http://localhost:8000/docs`](http://localhost:8000/docs)
ReDoc: [`http://localhost:8000/redoc`](http://localhost:8000/redoc)

---

## 🔌 API Overview

All endpoints are prefixed with `/api/v1/` and require Bearer token authentication.

**Header:**
```
Authorization: Bearer YOUR_API_KEY
```

### Core Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/chat` | Send a message and receive an AI response |
| `POST` | `/api/v1/ingest` | Upload PDF/DOCX for RAG indexing |
| `POST` | `/api/v1/leads` | Submit a lead capture form |
| `POST` | `/api/v1/telegram` | Telegram webhook receiver |
| `POST` | `/api/v1/woo-webhook` | WooCommerce event receiver |
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |

### Example: Chat Request

```bash
curl -X POST "http://localhost:8000/api/v1/chat" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{"question": "What is the price of product X?"}'
```

**Response:**
```json
{
  "answer": "Product X costs $49.99. Our supplier price is $42.00, giving you a margin of 16%.",
  "sources": ["catalog/product-x.pdf"],
  "session_id": "abc123"
}
```

> Full endpoint reference with schemas and error codes: [`docs/reference/api.md`](docs/reference/api.md)
> After starting the app, also see: [`http://localhost:8000/docs`](http://localhost:8000/docs)

---

## 🧠 RAG Architecture

BubbleBrain uses the **Retrieval-Augmented Generation** pattern to eliminate AI hallucinations:

```
User Question
     │
     ▼
[Embedding Model]  ←── text-embedding-3-small
     │
     ▼
[Pinecone Search]  ←── cosine similarity, top-k retrieval
     │
     ▼
[Context Assembly] ←── retrieved chunks + chat history
     │
     ▼
[OpenAI LLM]       ←──  GPT-4
     │
     ▼
Grounded Answer
```

1. **Ingestion** — documents are chunked, embedded, and stored in Pinecone
2. **Retrieval** — query is embedded; nearest vectors are fetched
3. **Generation** — LLM generates an answer strictly from retrieved context

See [`docs/explanation/rag-architecture.md`](docs/explanation/rag-architecture.md) for full details.

---

## ⚙️ Configuration Reference

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API key |
| `OPENAI_MODEL` | ✅ | LLM model (e.g. `gpt-3.5-turbo`) |
| `EMBEDDING_MODEL` | ✅ | Embedding model (e.g. `text-embedding-3-small`) |
| `PINECONE_API_KEY` | ✅ | Pinecone API key |
| `PINECONE_INDEX_NAME` | ✅ | Name of your Pinecone index |
| `PINECONE_ENVIRONMENT` | ✅ | e.g. `gcp-starter` |
| `API_KEY_SECRET` | ✅ | Static secret for client authentication |
| `WOO_CK` / `WOO_CS` | ⚠️ | WooCommerce consumer key/secret |
| `WOO_URL` | ⚠️ | WooCommerce store URL |
| `SUPPLIER_URL` | ⚠️ | Supplier site URL for price comparison |
| `SENTRY_DSN` | ❌ | Sentry error tracking DSN |
| `PROMETHEUS_EXTERNAL_URL` | ❌ | External URL for Prometheus |
| `ALLOWED_ORIGINS` | ❌ | CORS origins (default: `*`) |
| `TELEGRAM_CONTACT_URL` | ❌ | Telegram bot deep link |

---

## 🧪 Testing

```bash
# Run all tests with coverage report
poetry run pytest --cov=app --cov-report=term-missing

# Run only remote integration tests (requires running server)
poetry run pytest -m remote
```

**Current coverage: 88%** across 2,553 statements.

Key modules with full coverage: `main.py`, `health`, `security`, `metrics`, `woo_service`, `telegram_service`, `statistics_service`.

---

## 📊 Monitoring

BubbleBrain exposes Prometheus metrics at `/metrics` and includes a pre-configured Prometheus container.

| Service | Port | URL |
|---|---|---|
| BubbleBrain API | 8200 | `http://localhost:8200` |
| Prometheus | 9290 | `http://localhost:9290` |
| Swagger UI | 8200 | `http://localhost:8200/docs` |

Sentry integration is enabled when `SENTRY_DSN` is set in `.env`.

---

## 📁 Project Structure

```
BubbleBrain/
├── app/
│   ├── api/v1/endpoints/     # chat, ingest, leads, telegram, woo_webhook
│   ├── core/                 # config, db, security, logging, metrics
│   ├── middleware/           # rate limiter, request logging
│   ├── models/               # SQLAlchemy models
│   ├── schemas/              # Pydantic schemas
│   ├── services/             # RAG engine, OpenAI, vector, scraper, price comparator...
│   └── utils/                # helpers, prompts, URL utils
├── tests/
├── docs/                     # MkDocs documentation
├── prometheus/
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## 📚 Documentation

Full documentation is available via MkDocs:

```bash
poetry run mkdocs serve
```

Then open [`http://localhost:8001`](http://localhost:8001).

| Section | Description |
|---|---|
| [Getting Started](docs/tutorials/getting-started.md) | Run the stack locally in 10 minutes |
| [Configure Pinecone](docs/how-to/configure-pinecone.md) | Set up vector index for RAG |
| [API Reference](docs/reference/api.md) | Endpoint schemas and auth details |
| [RAG Architecture](docs/explanation/rag-architecture.md) | How the retrieval pipeline works |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit using [Conventional Commits](https://www.conventionalcommits.org/): `git commit -m "feat: add X"`
4. Push and open a Pull Request

Code quality is enforced via pre-commit hooks (Ruff, mypy, pyright):

```bash
pre-commit install
```

---

## 📄 License

[MIT](LICENSE) © [PyDevDeep](https://github.com/PyDevDeep)
