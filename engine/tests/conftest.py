from pathlib import Path
import pytest

_SEMANTIC_MAPPING_RESOURCES = Path(__file__).resolve().parents[1] / "resources" / "semantic_mapping"


@pytest.fixture(scope="session")
def stage3_db():
    return _SEMANTIC_MAPPING_RESOURCES / "bridge_semantic_source_v0.3.sqlite"


@pytest.fixture(scope="session")
def tamil_php_usfm():
    return _SEMANTIC_MAPPING_RESOURCES / "regression" / "51PHPIRVTam.SFM"


@pytest.fixture(scope="session")
def tamil_luk_usfm():
    return _SEMANTIC_MAPPING_RESOURCES / "regression" / "43LUKIRVTam.SFM"
