from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceReference(CatalogModel):
    path: str
    heading: str
    section_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class FilterOperator(StrEnum):
    EQ = "eq"
    IN = "in"
    LTE = "lte"
    BETWEEN = "between"


class FilterRule(CatalogModel):
    field: str
    operator: FilterOperator
    value: str | int | list[str | int]


class JoinRule(CatalogModel):
    left: str
    right: str


class ArithmeticExpression(CatalogModel):
    operator: str
    fields: list[str] = Field(min_length=2, max_length=2)


class RatioComponent(CatalogModel):
    metric: str
    filters: list[FilterRule] = Field(default_factory=list)


class MetricKind(StrEnum):
    AGGREGATE = "aggregate"
    RATIO = "ratio"


class MetricDefinition(CatalogModel):
    id: str
    label: str
    description: str
    kind: MetricKind
    synonyms: list[str] = Field(min_length=1)
    aggregation: str | None = None
    field: str | None = None
    expression: ArithmeticExpression | None = None
    filters: list[FilterRule] = Field(default_factory=list)
    joins: list[JoinRule] = Field(default_factory=list)
    numerator: RatioComponent | None = None
    denominator: RatioComponent | None = None
    zero_denominator: str | None = None
    data_sources: list[str] = Field(min_length=1)
    requires_wac: bool = False
    alternative_metric: str | None = None
    sources: list[SourceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_shape(self) -> "MetricDefinition":
        if self.kind is MetricKind.AGGREGATE:
            if not self.aggregation:
                raise ValueError("aggregate metrics require aggregation")
            if (self.field is None) == (self.expression is None):
                raise ValueError("aggregate metrics require exactly one field or expression")
            if self.numerator or self.denominator:
                raise ValueError("aggregate metrics cannot define ratio components")
        else:
            if not self.numerator or not self.denominator:
                raise ValueError("ratio metrics require numerator and denominator")
            if self.field or self.expression or self.aggregation:
                raise ValueError("ratio metrics cannot define aggregate fields")
        return self


class TimeWindowDefinition(CatalogModel):
    id: str
    label: str
    synonyms: list[str] = Field(min_length=1)
    filter: FilterRule
    notes: str | None = None
    sources: list[SourceReference] = Field(min_length=1)


class DimensionExpression(CatalogModel):
    function: str | None = None
    fields: list[str] = Field(min_length=1)


class DimensionDefinition(CatalogModel):
    id: str
    label: str
    synonyms: list[str] = Field(min_length=1)
    expression: DimensionExpression
    joins: list[JoinRule] = Field(default_factory=list)
    sources: list[SourceReference] = Field(min_length=1)


class DataSourceDefinition(CatalogModel):
    id: str
    label: str
    value: str
    synonyms: list[str] = Field(min_length=1)
    description: str
    include_by_default: bool
    wac_semantics: str
    sources: list[SourceReference] = Field(min_length=1)


class SecurityRule(CatalogModel):
    id: str
    roles: list[str] = Field(min_length=1)
    effect: str
    protected_field: str | None = None
    alternative_metric: str | None = None
    sources: list[SourceReference] = Field(min_length=1)


class CatalogDefaults(CatalogModel):
    metric: str
    time_window: str
    account_dimension: str


class DomainCatalog(CatalogModel):
    version: int
    schema_source: str
    defaults: CatalogDefaults
    metrics: list[MetricDefinition] = Field(min_length=1)
    time_windows: list[TimeWindowDefinition] = Field(min_length=1)
    dimensions: list[DimensionDefinition] = Field(min_length=1)
    data_sources: list[DataSourceDefinition] = Field(min_length=1)
    security_rules: list[SecurityRule] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "DomainCatalog":
        for label, definitions in (
            ("metric", self.metrics),
            ("time window", self.time_windows),
            ("dimension", self.dimensions),
            ("data source", self.data_sources),
            ("security rule", self.security_rules),
        ):
            ids = [definition.id for definition in definitions]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {label} ids")
        return self

    @property
    def metrics_by_id(self) -> dict[str, MetricDefinition]:
        return {item.id: item for item in self.metrics}

    @property
    def time_windows_by_id(self) -> dict[str, TimeWindowDefinition]:
        return {item.id: item for item in self.time_windows}

    @property
    def dimensions_by_id(self) -> dict[str, DimensionDefinition]:
        return {item.id: item for item in self.dimensions}

    @property
    def data_sources_by_id(self) -> dict[str, DataSourceDefinition]:
        return {item.id: item for item in self.data_sources}
