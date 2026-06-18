import re
import time
import uuid


def generate_document_id(filename: str) -> str:
    """Generation of a unique document ID based on the filename."""
    clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", filename.split(".")[0])
    return f"{clean_name}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
