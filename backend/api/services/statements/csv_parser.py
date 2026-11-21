import csv
import io
import re

from .normalization import MAX_ERRORS, MAX_ROWS, ParsedStatement, StatementError, normalize_row

ALIASES = {
    "date": {"date", "transaction date", "posting date", "value date", "book date", "booking date", "timestamp", "дата", "вальор", "дата на операцията"},
    "description": {"description", "details", "particulars", "merchant", "payee", "memo", "описание", "основание", "детайли"},
    "amount": {"amount", "signed amount", "transaction amount", "сума", "стойност"},
    "debit": {"debit", "debit amount", "withdrawal", "money out", "paid out", "дебит", "разход"},
    "credit": {"credit", "credit amount", "deposit", "money in", "paid in", "кредит", "приход"},
    "currency": {"currency", "ccy", "валута"},
    "direction": {"direction", "debit credit", "dr cr"},
    "category": {"category", "категория"},
}


def column_key(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def decode_csv(content):
    try:
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = content.decode("utf-16")
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("cp1251")
    except UnicodeError as error:
        raise StatementError("The statement could not be decoded as CSV.") from error
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        raise StatementError("The file contains binary or unsupported CSV content.")
    return text


def parse_table(headers, records, options):
    headers = tuple(value.strip() for value in headers)
    keys = [column_key(value) for value in headers]
    if not 2 <= len(headers) <= 100 or any(not value or len(value) > 128 for value in headers):
        raise StatementError("The statement must start with a valid column header row.")
    if len(set(header.casefold() for header in headers)) != len(headers):
        raise StatementError("CSV header names must be unique.")

    mapping = options.mapping
    if mapping is None:
        mapping = {
            field: headers[index]
            for field, aliases in ALIASES.items()
            if (index := next((i for i, key in enumerate(keys) if key in aliases), None)) is not None
        }
        if "amount" in mapping:
            mapping.pop("debit", None)
            mapping.pop("credit", None)
    if (
        not set(mapping) <= set(ALIASES)
        or any(not isinstance(value, str) or value not in headers for value in mapping.values())
        or len(set(mapping.values())) != len(mapping)
    ):
        raise StatementError("Column mapping must refer to distinct columns in this statement.")
    if not {"date", "description"} <= set(mapping) or not {"amount", "debit", "credit"} & set(mapping):
        return ParsedStatement([], [], headers, mapping, needs_mapping=True)
    if "amount" in mapping and {"debit", "credit"} & set(mapping):
        raise StatementError("Map a signed amount column or debit and credit columns.")
    if "direction" in mapping and "amount" not in mapping:
        raise StatementError("Use a debit and credit indicator with a signed amount column.")

    indexed = {field: headers.index(column) for field, column in mapping.items()}
    rows, errors = [], []
    for count, (line, values) in enumerate(records, 1):
        if count > MAX_ROWS:
            raise StatementError(f"Statements can contain at most {MAX_ROWS} transaction rows.")
        if not any(value.strip() for value in values):
            continue
        try:
            if len(values) != len(headers):
                raise ValueError("This row has a different number of columns than the header.")
            fields = {field: values[index].strip() for field, index in indexed.items()}
            rows.append(normalize_row(fields, default_currency=options.default_currency, date_order=options.date_order))
        except ValueError as error:
            if len(errors) < MAX_ERRORS:
                errors.append({"row": line, "message": str(error)})
    if not errors and not rows:
        raise StatementError("No transactions were found in the statement.")
    return ParsedStatement(rows, errors, headers, mapping)


class CsvStatementParser:
    def parse(self, content, options):
        text = decode_csv(content)
        try:
            # Examine the header alone so European decimal commas in later rows
            # cannot override a semicolon or tab delimiter.
            first_line = text.splitlines()[0] if text else ""
            dialect = csv.Sniffer().sniff(first_line, delimiters=";,\t")
            reader = csv.reader(io.StringIO(text, newline=""), dialect, strict=True)
            headers = next(reader)
            return parse_table(headers, ((reader.line_num, row) for row in reader), options)
        except (csv.Error, StopIteration) as error:
            raise StatementError("The CSV structure is malformed or the delimiter is unsupported.") from error
