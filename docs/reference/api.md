# API Reference

This is the technical reference for the available endpoints in BubbleBrain. The core documentation is generated automatically via Swagger UI.

## Swagger UI
You will find all details regarding requests, their types, and responses in the Swagger UI:
- **Local environment**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Alternative documentation (Redoc)**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Authentication
All requests to `/api/v1/*` require the use of an API key:
- **Header**: `Authorization`
- **Value**: `Bearer YOUR_API_KEY`

If the key is missing or invalid, you will receive a `401 Unauthorized` error.

## Rate Limiting
We use `slowapi` to limit the number of requests:
- Chat endpoints: **20 requests per minute** per IP address.
- If the limit is exceeded, the API will return a `429 Too Many Requests` error.
