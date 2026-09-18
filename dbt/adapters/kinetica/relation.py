from dataclasses import dataclass, field
from typing import FrozenSet, Tuple, Union

from dbt.adapters.base.relation import BaseRelation, Policy, RelationType

SerializableIterable = Union[Tuple, FrozenSet]


@dataclass
class KineticaQuotePolicy(Policy):
    # Kinetica has no database/catalog level, so it is never quoted nor rendered.
    database: bool = False
    schema: bool = True
    identifier: bool = True


@dataclass
class KineticaIncludePolicy(Policy):
    database: bool = False
    schema: bool = True
    identifier: bool = True


@dataclass(frozen=True, eq=False, repr=False)
class KineticaRelation(BaseRelation):
    quote_policy: Policy = field(default_factory=lambda: KineticaQuotePolicy())
    include_policy: Policy = field(default_factory=lambda: KineticaIncludePolicy())
    quote_character: str = '"'
    # Only tables can be renamed (ALTER TABLE ... RENAME TO); views and
    # materialized views are swapped with CREATE OR REPLACE instead.
    renameable_relations: SerializableIterable = field(
        default_factory=lambda: frozenset({RelationType.Table})
    )
    replaceable_relations: SerializableIterable = field(
        default_factory=lambda: frozenset(
            {RelationType.Table, RelationType.View, RelationType.MaterializedView}
        )
    )

    def qualified_name(self) -> str:
        """``schema.identifier`` without quotes, as Kinetica's native API expects."""
        if self.schema:
            return f"{self.schema}.{self.identifier}"
        return str(self.identifier)
