# How to Configure Pinecone for Vector Search

This guide will help you properly initialize a Pinecone index for use in the RAG module.

## Creating an Index
1. Go to your Pinecone dashboard.
2. Create a new index with the following parameters:
   - **Dimensions**: `1536` (if using the `text-embedding-3-small` model from OpenAI).
   - **Metric**: `cosine`.
3. Wait until the index status changes to "Ready".

## Project Configuration
Open the `.env` file and specify the name of the created index:

```env
PINECONE_INDEX_NAME="your-index-name"
PINECONE_ENVIRONMENT="gcp-starter" # or another region according to your account
```

## Testing the Connection
To verify that everything is configured correctly, run the initialization script:

```bash
poetry run python -m app.services.vector_service
```

If you see `Connected to Pinecone successfully`, the setup is complete.
