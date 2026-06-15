from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import Settings, get_settings
from app.core.logging_config import get_logger
from app.core.security import verify_api_key
from app.schemas.ingest import IngestResponse, TextIngestRequest
from app.services.document_processor import chunk_text, extract_text
from app.services.openai_service import OpenAIService
from app.services.vector_service import VectorService
from app.utils.helpers import generate_document_id

logger = get_logger(__name__)
ingest_router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def get_openai_service(settings: Settings = Depends(get_settings)) -> OpenAIService:
    return OpenAIService(settings)


def get_vector_service(settings: Settings = Depends(get_settings)) -> VectorService:
    return VectorService(settings)


@ingest_router.post("/document", response_model=IngestResponse)
async def upload_document(
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key),
    openai_service: OpenAIService = Depends(get_openai_service),
    vector_service: VectorService = Depends(get_vector_service),
) -> IngestResponse:

    filename = file.filename or "unknown"
    logger.info("Starting document ingestion", filename=filename)

    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE / 1024 / 1024}MB",
        )

    try:
        text = await extract_text(file)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    document_id = generate_document_id(filename)
    chunks = chunk_text(text)

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No extractable text found"
        )

    try:
        embeddings = await openai_service.generate_embeddings_batch(chunks)

        vectors: list[tuple[str, list[float], dict[str, Any]]] = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=True)):
            chunk_id = f"{document_id}_chunk_{i}"
            metadata: dict[str, Any] = {"text": chunk, "source": document_id, "chunk_index": i}
            vectors.append((chunk_id, emb, metadata))

        await vector_service.upsert_vectors(vectors)
        logger.info("Document ingested successfully", document_id=document_id, chunks=len(chunks))

        return IngestResponse(document_id=document_id, chunks_count=len(chunks), status="indexed")

    except Exception as e:
        logger.error("Ingestion pipeline failed", error=str(e), document_id=document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process document"
        ) from e


@ingest_router.post("/text", response_model=IngestResponse)
async def upload_text(
    request: TextIngestRequest,
    api_key: str = Depends(verify_api_key),
    openai_service: OpenAIService = Depends(get_openai_service),
    vector_service: VectorService = Depends(get_vector_service),
) -> IngestResponse:

    logger.info("Starting text ingestion")
    document_id = generate_document_id("raw_text")
    chunks = chunk_text(request.text)

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Text is too short to process"
        )

    try:
        embeddings = await openai_service.generate_embeddings_batch(chunks)

        vectors: list[tuple[str, list[float], dict[str, Any]]] = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=True)):
            chunk_id = f"{document_id}_chunk_{i}"
            metadata: dict[str, Any] = {"text": chunk, "source": document_id, "chunk_index": i}
            if request.metadata:
                metadata.update(request.metadata)
            vectors.append((chunk_id, emb, metadata))

        await vector_service.upsert_vectors(vectors)
        logger.info("Text ingested successfully", document_id=document_id, chunks=len(chunks))

        return IngestResponse(document_id=document_id, chunks_count=len(chunks), status="indexed")

    except Exception as e:
        logger.error("Text ingestion failed", error=str(e), document_id=document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process text"
        ) from e
