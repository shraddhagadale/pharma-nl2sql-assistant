from pathlib import Path

from app.domain.catalog import CatalogRepository, CatalogValidator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "domain" / "domain_catalog.yaml"


def test_catalog_loads_and_resolves_cross_references() -> None:
    catalog = CatalogRepository.load(CATALOG_PATH, project_root=PROJECT_ROOT)

    assert len(catalog.metrics) == 5
    assert len(catalog.time_windows) == 8
    assert len(catalog.dimensions) == 7
    assert len(catalog.data_sources) == 3
    assert catalog.metrics_by_id["market_share"].denominator.metric == "equivalents"
    assert catalog.defaults.metric == "paid_demand"


def test_validator_rejects_stale_source_provenance() -> None:
    catalog = CatalogRepository.load(CATALOG_PATH, project_root=PROJECT_ROOT)
    metric = catalog.metrics_by_id["paid_demand"]
    stale_source = metric.sources[0].model_copy(update={"section_sha256": "0" * 64})
    stale_metric = metric.model_copy(update={"sources": [stale_source]})
    stale_catalog = catalog.model_copy(
        update={
            "metrics": [
                stale_metric if item.id == stale_metric.id else item for item in catalog.metrics
            ]
        }
    )

    issues = CatalogValidator(PROJECT_ROOT).validate(stale_catalog)

    assert any("stale provenance" in issue for issue in issues)


def test_validator_rejects_unknown_schema_field() -> None:
    catalog = CatalogRepository.load(CATALOG_PATH, project_root=PROJECT_ROOT)
    metric = catalog.metrics_by_id["paid_demand"].model_copy(update={"field": "sales.not_a_column"})
    invalid_catalog = catalog.model_copy(
        update={"metrics": [metric if item.id == metric.id else item for item in catalog.metrics]}
    )

    issues = CatalogValidator(PROJECT_ROOT).validate(invalid_catalog)

    assert "unknown column in field reference: sales.not_a_column" in issues
