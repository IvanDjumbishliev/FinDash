import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from django.core.files.uploadhandler import FileUploadHandler, StopUpload

from .csv_parser import CsvStatementParser
from .normalization import ParsedStatement, StatementError, currency_code
from .pdf_parser import PdfStatementParser

MAX_FILE_BYTES = 10 * 1024 * 1024

MIME_TYPES = {
    "csv": {"text/csv", "application/csv", "text/plain", "text/comma-separated-values", "application/vnd.ms-excel", "application/octet-stream"},
    "pdf": {"application/pdf", "application/x-pdf", "application/octet-stream"},
}


@dataclass(frozen=True)
class ParseOptions:
    mapping: dict | None = None
    default_currency: str | None = None
    date_order: str = "DMY"
    allow_external_processing: bool = False
    allow_ai_categorization: bool = False


class StatementParser(Protocol):
    def parse(self, content: bytes, options: ParseOptions) -> ParsedStatement: ...


PARSERS: dict[str, StatementParser] = {"csv": CsvStatementParser(), "pdf": PdfStatementParser()}


class StatementSizeLimit(FileUploadHandler):
    def __init__(self, request):
        super().__init__(request)
        self.received = 0
        self.exceeded = False

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_FILE_BYTES:
            self.exceeded = True
            raise StopUpload()
        return raw_data

    def file_complete(self, file_size):
        return None


def parse_options(data):
    mapping = data.get("mapping")
    if isinstance(mapping, str):
        if len(mapping) > 4096:
            raise StatementError("Column mapping is too large.")
        try:
            mapping = json.loads(mapping)
        except (ValueError, RecursionError) as error:
            raise StatementError("Column mapping must be a JSON object.") from error
    if mapping is not None and not isinstance(mapping, dict):
        raise StatementError("Column mapping must be a JSON object.")
    date_order = data.get("date_order", "DMY")
    if date_order not in ("DMY", "MDY"):
        raise StatementError("Choose either day-first or month-first dates.")
    def consent(flag):
        value = data.get(flag, False)
        if type(value) is bool:
            return value
        if isinstance(value, str) and value in {"true", "false"}:
            return value == "true"
        raise StatementError("External processing consent must be true or false.")
    try:
        default_currency = currency_code(data["default_currency"]) if data.get("default_currency") else None
    except ValueError as error:
        raise StatementError(str(error)) from error
    return ParseOptions(
        mapping=mapping, default_currency=default_currency, date_order=date_order,
        allow_external_processing=consent("allow_external_processing"),
        allow_ai_categorization=consent("allow_ai_categorization"),
    )


def upload_content(uploaded, *, allowed_formats):
    file_format = Path(uploaded.name).suffix.lower().lstrip(".")
    if file_format not in allowed_formats:
        accepted = " or ".join(fmt.upper() for fmt in sorted(allowed_formats))
        raise StatementError(f"Choose a supported {accepted} file.", status=415)
    if (uploaded.content_type or "").lower().split(";", 1)[0].strip() not in MIME_TYPES[file_format]:
        raise StatementError("The declared file type does not match the statement extension.", status=415)
    if uploaded.size > MAX_FILE_BYTES:
        raise StatementError("Statements must be 10 MB or smaller.", status=413)
    content = uploaded.read(MAX_FILE_BYTES + 1)
    if not content:
        raise StatementError("The statement is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise StatementError("Statements must be 10 MB or smaller.", status=413)
    if file_format == "csv" and content.startswith((b"%PDF-", b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"MZ")):
        raise StatementError("The file contents do not match CSV.", status=415)
    return file_format, content
