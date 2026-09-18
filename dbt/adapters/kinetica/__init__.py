from dbt.adapters.base import AdapterPlugin

from dbt.adapters.kinetica.column import KineticaColumn  # noqa: F401
from dbt.adapters.kinetica.connections import (  # noqa: F401
    KineticaConnectionManager,
    KineticaCredentials,
)
from dbt.adapters.kinetica.impl import KineticaAdapter  # noqa: F401
from dbt.adapters.kinetica.relation import KineticaRelation  # noqa: F401
from dbt.include import kinetica

Plugin = AdapterPlugin(
    adapter=KineticaAdapter,  # type: ignore[arg-type]
    credentials=KineticaCredentials,
    include_path=kinetica.PACKAGE_PATH,
)
