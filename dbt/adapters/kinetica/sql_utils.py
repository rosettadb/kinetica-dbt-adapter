"""Pure helpers for the Kinetica adapter: statement splitting, literal rendering
and Kinetica -> SQL type mapping.  Nothing in here touches the network, so it is
all unit-testable without a server."""

import datetime
import decimal
import math
import re
from typing import Any, Iterable, List, Optional, Sequence, Tuple

#: Kinetica's plain ``string`` type has no declared length.  dbt's column
#: expansion logic needs *some* integer, so we use this sentinel and translate
#: it back to an unbounded ``varchar`` when rendering DDL.
UNBOUNDED_STRING_SIZE = 2**31 - 1

_TRANSACTION_CONTROL = {
    "begin",
    "begin transaction",
    "begin work",
    "start transaction",
    "commit",
    "commit transaction",
    "commit work",
    "end",
    "end transaction",
    "rollback",
    "rollback transaction",
    "rollback work",
}

_QUERY_KEYWORDS = {"select", "with", "values", "show", "describe", "desc", "explain", "("}


def split_sql_statements(sql: str) -> List[str]:
    """Split ``sql`` on semicolons that are outside of quotes and comments.

    Kinetica's ``/execute/sql`` endpoint runs exactly one statement per call, but
    several dbt macros emit ``stmt1; stmt2`` blocks.  Empty chunks and chunks
    that consist solely of comments/whitespace are dropped."""
    statements: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(sql)
    in_single = in_double = in_line_comment = in_block_comment = False

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 1
                in_block_comment = False
        elif in_single:
            buf.append(ch)
            if ch == "'":
                if nxt == "'":
                    buf.append(nxt)
                    i += 1
                else:
                    in_single = False
        elif in_double:
            buf.append(ch)
            if ch == '"':
                if nxt == '"':
                    buf.append(nxt)
                    i += 1
                else:
                    in_double = False
        else:
            if ch == "-" and nxt == "-":
                in_line_comment = True
                buf.append(ch)
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                buf.append(ch)
            elif ch == "'":
                in_single = True
                buf.append(ch)
            elif ch == '"':
                in_double = True
                buf.append(ch)
            elif ch == ";":
                statements.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        i += 1

    statements.append("".join(buf))
    return [s.strip() for s in statements if not is_blank_sql(s)]


def strip_sql_comments(sql: str) -> str:
    """Remove ``--`` and ``/* */`` comments (outside of string literals)."""
    out: List[str] = []
    i = 0
    n = len(sql)
    in_single = in_double = False
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if in_single:
            out.append(ch)
            if ch == "'":
                in_single = False
        elif in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
        elif ch == "-" and nxt == "-":
            end = sql.find("\n", i)
            i = n if end == -1 else end
            continue
        elif ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            out.append(ch)
        i += 1
    return "".join(out)


def is_blank_sql(sql: str) -> bool:
    return strip_sql_comments(sql).strip() == ""


def first_keyword(sql: str) -> str:
    """Lower-cased first token of the statement (comments ignored)."""
    body = strip_sql_comments(sql).strip()
    if not body:
        return ""
    if body[0] == "(":
        return "("
    match = re.match(r"[A-Za-z_]+", body)
    return match.group(0).lower() if match else ""


def is_transaction_control(sql: str) -> bool:
    """Kinetica auto-commits; BEGIN/COMMIT/ROLLBACK are silently skipped."""
    body = " ".join(strip_sql_comments(sql).strip().rstrip(";").lower().split())
    return body in _TRANSACTION_CONTROL


def looks_like_query(sql: str) -> bool:
    return first_keyword(sql) in _QUERY_KEYWORDS


# --------------------------------------------------------------------------- #
# Literal rendering (seeds, parameter binding)
# --------------------------------------------------------------------------- #


def render_literal(value: Any) -> str:
    """Render a Python value as a Kinetica SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        # Kinetica's BOOLEAN is an int8 under the hood; 1/0 is accepted everywhere.
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "NULL"
        return repr(value)
    if isinstance(value, decimal.Decimal):
        if value.is_nan() or value.is_infinite():
            return "NULL"
        return format(value, "f")
    if isinstance(value, datetime.datetime):
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S.") + f"{value.microsecond // 1000:03d}'"
    if isinstance(value, datetime.date):
        return "'" + value.isoformat() + "'"
    if isinstance(value, datetime.time):
        return "'" + value.strftime("%H:%M:%S.") + f"{value.microsecond // 1000:03d}'"
    if isinstance(value, (bytes, bytearray)):
        return "'" + bytes(value).decode("utf-8", errors="replace").replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def bind_parameters(sql: str, bindings: Optional[Sequence[Any]]) -> str:
    """Substitute ``%s`` placeholders (pyformat style) with rendered literals.
    ``%%`` is an escaped percent sign."""
    if not bindings:
        return sql
    values = list(bindings)
    out: List[str] = []
    i = 0
    n = len(sql)
    idx = 0
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "%" and nxt == "s":
            if idx >= len(values):
                raise ValueError("Not enough bindings for the SQL placeholders")
            out.append(render_literal(values[idx]))
            idx += 1
            i += 2
            continue
        if ch == "%" and nxt == "%":
            out.append("%")
            i += 2
            continue
        out.append(ch)
        i += 1
    if idx != len(values):
        raise ValueError("Too many bindings for the SQL placeholders")
    return "".join(out)


# --------------------------------------------------------------------------- #
# Type mapping
# --------------------------------------------------------------------------- #

_BASE_TYPES = {
    "int": "integer",
    "long": "bigint",
    "float": "real",
    "double": "double",
    "string": "varchar",
    "bytes": "blob",
}

# Kinetica "column properties" (and the datatype names returned in JSON result
# sets) that refine a base type into a concrete SQL type.
_PROPERTY_TYPES = {
    "int8": "tinyint",
    "int16": "smallint",
    "boolean": "boolean",
    "ulong": "unsigned bigint",
    "timestamp": "timestamp",
    "date": "date",
    "datetime": "datetime",
    "time": "time",
    "uuid": "uuid",
    "ipv4": "ipv4",
    "wkt": "geometry",
    "geometry": "geometry",
    "json": "json",
}

_CHAR_RE = re.compile(r"char(\d+)")
_DECIMAL_RE = re.compile(r"decimal(?:\((\d+)\s*,\s*(\d+)\))?")
_VECTOR_RE = re.compile(r"vector\((\d+)\)")
_ARRAY_RE = re.compile(r"array\(([A-Za-z0-9_]+)\)")

DEFAULT_DECIMAL_PRECISION = 18
DEFAULT_DECIMAL_SCALE = 4

TypeInfo = Tuple[str, Optional[int], Optional[int], Optional[int]]


def map_kinetica_type(base_type: Optional[str], properties: Iterable[str] = ()) -> TypeInfo:
    """Translate a Kinetica column (Avro base type + column properties, or a
    JSON result-set datatype name) into ``(dtype, char_size, precision, scale)``
    using SQL type names that Kinetica's DDL accepts."""
    base = (base_type or "").strip().lower()
    tokens = [base] + [str(p).strip().lower() for p in properties if p is not None]

    for token in tokens:
        if not token:
            continue
        if token in _PROPERTY_TYPES:
            return _PROPERTY_TYPES[token], None, None, None
        m = _CHAR_RE.fullmatch(token)
        if m:
            return "varchar", int(m.group(1)), None, None
        m = _DECIMAL_RE.fullmatch(token)
        if m:
            precision = int(m.group(1)) if m.group(1) else DEFAULT_DECIMAL_PRECISION
            scale = int(m.group(2)) if m.group(2) else DEFAULT_DECIMAL_SCALE
            return "decimal", None, precision, scale
        m = _VECTOR_RE.fullmatch(token)
        if m:
            return f"vector({m.group(1)})", None, None, None
        m = _ARRAY_RE.fullmatch(token)
        if m:
            element = map_kinetica_type(m.group(1))[0]
            return f"{element}[]", None, None, None

    if base in _BASE_TYPES:
        return _BASE_TYPES[base], None, None, None
    # Unknown: hand the raw name back so nothing is silently lost.
    return (base or "varchar"), None, None, None


_EPOCH = datetime.datetime(1970, 1, 1)


def _parse_datetime(value: Any) -> Any:
    if value is None or isinstance(value, datetime.datetime):
        return value
    if isinstance(value, (int, float)):
        return _EPOCH + datetime.timedelta(milliseconds=value)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return value


def _parse_date(value: Any) -> Any:
    if value is None or isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return value


def _parse_time(value: Any) -> Any:
    if value is None or isinstance(value, datetime.time):
        return value
    text = str(value).strip()
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return value


def _parse_decimal(value: Any) -> Any:
    if value is None or isinstance(value, decimal.Decimal):
        return value
    try:
        return decimal.Decimal(str(value))
    except (decimal.InvalidOperation, ValueError):
        return value


def _parse_bool(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "t", "yes")
    return bool(value)


def value_converter(kinetica_datatype: Optional[str]):
    """Return a callable that converts a JSON-decoded Kinetica value into the
    most natural Python object, or ``None`` when no conversion is needed."""
    dt = (kinetica_datatype or "").strip().lower()
    if dt == "timestamp":
        return _parse_datetime
    if dt == "datetime":
        return _parse_datetime
    if dt == "date":
        return _parse_date
    if dt == "time":
        return _parse_time
    if dt == "boolean":
        return _parse_bool
    if dt.startswith("decimal"):
        return _parse_decimal
    return None


def split_qualified_name(name: str, default_schema: Optional[str]) -> Tuple[Optional[str], str]:
    """``schema.table`` -> ``(schema, table)``; bare names get ``default_schema``."""
    if "." in name:
        schema, identifier = name.split(".", 1)
        return schema, identifier
    return default_schema, name
