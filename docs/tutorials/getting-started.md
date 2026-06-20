# Tutorial: Running BubbleBrain in 10 Minutes

**What you will build**: A working local AI server with a connected RAG engine and OpenAPI Swagger UI, capable of answering product queries.

**What you will learn**:
- How to initialize the Poetry environment
- How to start necessary Docker containers
- How to make your first API request

**Prerequisites**:
- [ ] Python 3.13+ installed
- [ ] Docker and Docker Compose installed
- [ ] OpenAI and Pinecone API keys

---

## Step 1: Environment Setup
First, you will configure environment variables so the application can communicate with external services.

Copy the `.env.example` file:

```bash
cp .env.example .env
```

> **Tip**: If an error occurs, make sure the `.env.example` file exists in the root directory of your project.

Open the `.env` file and insert your keys:
```env
OPENAI_API_KEY="sk-..."
PINECONE_API_KEY="pc-..."
```

---

## Step 2: Starting Containers
To allow the application to cache data, we will start Redis.

```bash
docker-compose up -d
```

You will see the following output:
```
[+] Running 1/1
 ✔ Container redis-stack  Started
```

---

## Step 3: Starting the Server
Finally, we will start the FastAPI development server.

```bash
poetry install
poetry run uvicorn app.main:app --reload
```

After this, you will have a working API accessible at `http://localhost:8000`.
To see the generated Swagger UI, navigate to `http://localhost:8000/docs` in your browser.
