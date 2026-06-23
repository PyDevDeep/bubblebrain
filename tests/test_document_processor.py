from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import UploadFile

from app.services.document_processor import chunk_text, extract_text


@pytest.mark.asyncio
async def test_extract_text_txt():
    # Arrange
    content = b"This is a test document."
    mock_file = Mock(spec=UploadFile)
    mock_file.content_type = "text/plain"
    mock_file.filename = "test.txt"

    read_called = False

    async def mock_read(size=-1):
        nonlocal read_called
        if not read_called:
            read_called = True
            return content
        return b""

    mock_file.read = mock_read

    # Act
    result = await extract_text(mock_file)

    # Assert
    assert result == "This is a test document."


@pytest.mark.asyncio
@patch("app.services.document_processor.pdfplumber.open")
async def test_extract_text_pdf(mock_pdfplumber_open):
    # Arrange
    content = b"fake pdf content"
    mock_file = Mock(spec=UploadFile)
    mock_file.content_type = "application/pdf"
    mock_file.filename = "test.pdf"

    read_called = False

    async def mock_read(size=-1):
        nonlocal read_called
        if not read_called:
            read_called = True
            return content
        return b""

    mock_file.read = mock_read

    mock_pdf = MagicMock()
    mock_page1 = Mock()
    mock_page1.extract_text.return_value = "Page 1 text"
    mock_page2 = Mock()
    mock_page2.extract_text.return_value = "Page 2 text"

    mock_pdf.pages = [mock_page1, mock_page2]
    mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf

    # Act
    result = await extract_text(mock_file)

    # Assert
    assert result == "Page 1 text\n\nPage 2 text"


@pytest.mark.asyncio
@patch("app.services.document_processor.Document")
async def test_extract_text_docx(mock_document_class):
    # Arrange
    content = b"fake docx content"
    mock_file = Mock(spec=UploadFile)
    mock_file.content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    mock_file.filename = "test.docx"

    read_called = False

    async def mock_read(size=-1):
        nonlocal read_called
        if not read_called:
            read_called = True
            return content
        return b""

    mock_file.read = mock_read

    mock_doc = MagicMock()
    mock_p1 = Mock()
    mock_p1.text = "Paragraph 1"
    mock_p2 = Mock()
    mock_p2.text = "Paragraph 2"
    mock_doc.paragraphs = [mock_p1, mock_p2]

    mock_document_class.return_value = mock_doc

    # Act
    result = await extract_text(mock_file)

    # Assert
    assert result == "Paragraph 1\n\nParagraph 2"


@pytest.mark.asyncio
async def test_extract_text_unsupported_type():
    # Arrange
    mock_file = Mock(spec=UploadFile)
    mock_file.content_type = "image/png"
    mock_file.filename = "image.png"

    read_called = False

    async def mock_read(size=-1):
        nonlocal read_called
        if not read_called:
            read_called = True
            return b"fake image"
        return b""

    mock_file.read = mock_read

    # Act & Assert
    with pytest.raises(ValueError, match="Unsupported file type: image/png"):
        await extract_text(mock_file)


@pytest.mark.asyncio
async def test_extract_text_empty_file():
    # Arrange
    mock_file = Mock(spec=UploadFile)
    mock_file.content_type = "text/plain"
    mock_file.filename = "empty.txt"

    async def mock_read(size=-1):
        return b""

    mock_file.read = mock_read

    # Act & Assert
    with pytest.raises(ValueError, match="Empty document"):
        await extract_text(mock_file)


def test_chunk_text_basic():
    # Arrange
    text = " ".join([f"This is sentence number {i} to make it long enough." for i in range(10)])
    # Act
    # chunk_size in chunks logic: max_chars = chunk_size * 4 = 10 * 4 = 40
    result = chunk_text(text, chunk_size=10, overlap=2)

    # Assert
    assert len(result) > 1
    assert "This is sentence" in result[0]


def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []
