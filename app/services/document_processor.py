import io
import re

import pdfplumber
from docx import Document
from fastapi import UploadFile

from app.core.logging_config import get_logger

logger = get_logger(__name__)


async def extract_text(file: UploadFile) -> str:
    """
    Витягування тексту з файлу залежно від MIME-типу (PDF, TXT, DOCX, MD).
    Завантажує файл у пам'ять для уникнення блокування Event Loop.
    """
    content_type = file.content_type
    content = await file.read()

    if not content:
        raise ValueError("Empty document")

    text = ""
    filename = file.filename or ""
    filename_lower = filename.lower()

    try:
        # Markdown файли можуть передаватися з різними MIME-типами, тому перевіряємо і розширення
        if content_type in ("text/plain", "text/markdown") or filename_lower.endswith(
            (".txt", ".md")
        ):
            text = content.decode("utf-8")

        elif content_type == "application/pdf" or filename_lower.endswith(".pdf"):
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages_text: list[str] = []
                for page in pdf.pages:
                    page_text = str(page.extract_text()) if page.extract_text() else ""
                    if page_text:
                        pages_text.append(page_text)
                text = "\n\n".join(pages_text)

        elif (
            content_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or filename_lower.endswith(".docx")
        ):
            doc = Document(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n\n".join(paragraphs)

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
    Розбиття тексту на чанки з перекриттям для збереження контексту.
    Базується на розбитті по реченнях з урахуванням ліміту символів (~ токенів * 4).
    """
    if not text or not text.strip():
        return []

    # Розбиття по реченнях із збереженням розділових знаків
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
