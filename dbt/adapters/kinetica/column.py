from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Optional

from dbt.adapters.base.column import Column
from dbt_common.exceptions import DbtRuntimeError

from dbt.adapters.kinetica.sql_utils import UNBOUNDED_STRING_SIZE


@dataclass
class KineticaColumn(Column):
    TYPE_LABELS: ClassVar[Dict[str, str]] = {
        "STRING": "varchar",
        "TEXT": "varchar",
        "INT": "integer",
        "LONG": "bigint",
        "FLOAT": "double",
        "NUMERIC": "decimal",
    }

    _STRING_TYPES: ClassVar[tuple] = (
        "varchar",
        "string",
        "text",
        "char",
        "character",
        "character varying",
    )
    _INTEGER_TYPES: ClassVar[tuple] = (
        "integer",
        "int",
        "bigint",
        "long",
        "smallint",
        "tinyint",
        "int8",
        "int16",
        "unsigned bigint",
        "ulong",
    )
    _FLOAT_TYPES: ClassVar[tuple] = ("real", "float", "double", "double precision")
    _NUMERIC_TYPES: ClassVar[tuple] = ("decimal", "numeric")

    @property
    def quoted(self) -> str:
        return '"{}"'.format(self.column)

    def is_string(self) -> bool:
        return self.dtype.lower() in self._STRING_TYPES

    def is_integer(self) -> bool:
        return self.dtype.lower() in self._INTEGER_TYPES

    def is_float(self) -> bool:
        return self.dtype.lower() in self._FLOAT_TYPES

    def is_numeric(self) -> bool:
        return self.dtype.lower() in self._NUMERIC_TYPES

    def string_size(self) -> int:
        if not self.is_string():
            raise DbtRuntimeError("Called string_size() on non-string field!")
        if self.char_size is None:
            return UNBOUNDED_STRING_SIZE
        return int(self.char_size)

    def can_expand_to(self, other_column: "Column") -> bool:
        if not self.is_string() or not other_column.is_string():
            return False
        return other_column.string_size() > self.string_size()

    @classmethod
    def string_type(cls, size: Optional[int]) -> str:
        if size is None or size >= UNBOUNDED_STRING_SIZE or size <= 0:
            return "varchar"
        return "varchar({})".format(size)

    @classmethod
    def numeric_type(cls, dtype: str, precision: Any, scale: Any) -> str:
        if precision is None or scale is None:
            return dtype
        return "{}({},{})".format(dtype, precision, scale)

    def literal(self, value: Any) -> str:
        return "cast({} as {})".format(value, self.data_type)
