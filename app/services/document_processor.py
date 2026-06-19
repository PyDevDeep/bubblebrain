import asyncio
import io
import re

import pdfplumber
from docx import Document
from fastapi import UploadFile

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def _parse_pdf(content: bytes) -> str:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages_text: list[str] = []
        for page in pdf.pages:
            page_text = str(page.extract_text()) if page.extract_text() else ""
            if page_text:
                pages_text.append(page_text)
        return "\n\n".join(pages_text)


def _parse_docx(content: bytes) -> str:
    doc = Document(io.BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


async def extract_text(file: UploadFile) -> str:
    """
    Extract text from a file depending on its MIME type (PDF, TXT, DOCX, MD).
    Loads the file into memory to avoid blocking the Event Loop.
    """
    content_type = file.content_type
    content = await file.read()

    if not content:
        raise ValueError("Empty document")

    text = ""
    filename = file.filename or ""
    filename_lower = filename.lower()

    try:
        # Markdown files can be sent with different MIME types, so we also check the extension
        if content_type in ("text/plain", "text/markdown") or filename_lower.endswith(
            (".txt", ".md")
        ):
            text = content.decode("utf-8", errors="replace")

        elif content_type == "application/pdf" or filename_lower.endswith(".pdf"):
            text = await asyncio.to_thread(_parse_pdf, content)

        elif (
            content_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or filename_lower.endswith(".docx")
        ):
            text = await asyncio.to_thread(_parse_docx, content)

        else:
            raise ValueError(f"Unsupported file type: {content_type}")

    except Exception as e:
        if isinstance(e, ValueError):
            raise
        logger.error("Failed to parse document", error=str(e), filename=filename)
        raise ValueError("Failed to parse document content") from e

    text = text.strip()
    if not text:
        raise ValueError("Empty document")

    return text


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    """
    Split text into chunks with overlap to preserve context.
    Based on splitting by sentences taking into account the character limit (~ tokens * 4).
    """
    if not text or not text.strip():
        return []

    # Split by sentences preserving punctuation marks
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    max_chars = chunk_size * 4
    overlap_chars = overlap * 4

    chunks: list[str] = []
    current_chunk_sentences: list[str] = []
    current_length = 0

    i = 0
    while i < len(sentences):
        sentence = sentences[i]
        sentence_len = len(sentence)

        if sentence_len > max_chars:
            pieces = [sentence[j : j + max_chars] for j in range(0, sentence_len, max_chars)]
            sentences[i : i + 1] = pieces
            continue

        if current_length + sentence_len > max_chars and current_chunk_sentences:
            chunks.append(" ".join(current_chunk_sentences))

            overlap_length = 0
            overlap_sentences: list[str] = []

            for s in reversed(current_chunk_sentences):
                if overlap_length + len(s) <= overlap_chars:
                    overlap_sentences.insert(0, s)
                    overlap_length += len(s) + 1
                else:
                    break

            current_chunk_sentences = overlap_sentences
            current_length = overlap_length

        current_chunk_sentences.append(sentence)
        current_length += sentence_len + 1
        i += 1

    if current_chunk_sentences:
        final_chunk = " ".join(current_chunk_sentences)
        if len(final_chunk) < 50 and chunks:
            chunks[-1] = f"{chunks[-1]} {final_chunk}"
        else:
            chunks.append(final_chunk)

    return chunks
