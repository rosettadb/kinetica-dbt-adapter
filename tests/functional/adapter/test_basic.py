import pytest
from dbt.tests.adapter.basic.test_adapter_methods import BaseAdapterMethod
from dbt.tests.adapter.basic.test_base import BaseSimpleMaterializations
from dbt.tests.adapter.basic.test_empty import BaseEmpty
from dbt.tests.adapter.basic.test_ephemeral import BaseEphemeral
from dbt.tests.adapter.basic.test_generic_tests import BaseGenericTests
from dbt.tests.adapter.basic.test_incremental import BaseIncremental, BaseIncrementalNotSchemaChange
from dbt.tests.adapter.basic.test_singular_tests import BaseSingularTests
from dbt.tests.adapter.basic.test_singular_tests_ephemeral import BaseSingularTestsEphemeral
from dbt.tests.adapter.basic.test_snapshot_check_cols import BaseSnapshotCheckCols
from dbt.tests.adapter.basic.test_snapshot_timestamp import BaseSnapshotTimestamp
from dbt.tests.adapter.basic.test_table_materialization import BaseTableMaterialization
from dbt.tests.adapter.basic.test_validate_connection import BaseValidateConnection

pytestmark = pytest.mark.functional


class TestValidateConnectionKinetica(BaseValidateConnection):
    pass


class TestSimpleMaterializationsKinetica(BaseSimpleMaterializations):
    pass


class TestSingularTestsKinetica(BaseSingularTests):
    pass


class TestSingularTestsEphemeralKinetica(BaseSingularTestsEphemeral):
    pass


class TestEmptyKinetica(BaseEmpty):
    pass


class TestEphemeralKinetica(BaseEphemeral):
    pass


class TestIncrementalKinetica(BaseIncremental):
    pass


class TestIncrementalNotSchemaChangeKinetica(BaseIncrementalNotSchemaChange):
    pass


class TestGenericTestsKinetica(BaseGenericTests):
    pass


class TestSnapshotCheckColsKinetica(BaseSnapshotCheckCols):
    pass


class TestSnapshotTimestampKinetica(BaseSnapshotTimestamp):
    pass


class TestBaseAdapterMethodKinetica(BaseAdapterMethod):
    pass


class TestTableMaterializationKinetica(BaseTableMaterialization):
    pass
