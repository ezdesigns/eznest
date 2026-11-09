"""Bound in-memory JSON transport; binary PDF uploads use available disk."""

MAX_PDF_BYTES = None  # Streamed uploads have no fixed file-size ceiling.
MAX_JSON_PDF_BYTES = 256_000_000
MAX_PDF_BASE64_CHARS = 4 * ((MAX_JSON_PDF_BYTES + 2) // 3)
MAX_IMPORT_REQUEST_BYTES = MAX_PDF_BASE64_CHARS + 1_000_000


def request_limit(path):
    if path == '/api/document/import-file':
        return MAX_PDF_BYTES
    if path in ('/api/document/import', '/api/illustrator/intake'):
        return MAX_IMPORT_REQUEST_BYTES
    return 48_000_000
