import re
import time
import uuid


def generate_document_id(filename: str) -> str:
    """Генерація унікального ID документа на основі імені файлу."""
    clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", filename.split(".")[0])
    return f"{clean_name}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
