from app.models import UserRole

ANALYTICS_SCHEMA: dict[str, tuple[str, ...]] = {
    "organizations": (
        "org_id",
        "org_name",
        "org_type",
        "org_status",
        "org_archetype",
        "specialty",
        "city",
        "state",
        "zip",
        "parent_org_id",
        "parent_org_name",
        "grandparent_org_id",
        "grandparent_org_name",
        "gpo_name",
        "is_340b",
    ),
    "products": (
        "ndc",
        "drug_name",
        "generic_name",
        "strength",
        "form",
        "brand_flag",
        "specialty",
        "market_category",
        "market_subcategory",
        "unit_conversion_factor",
        "mg_equivalent",
    ),
    "zip_territory": (
        "zip",
        "state",
        "territory_number",
        "territory_name",
        "region_number",
        "region_name",
    ),
    "sales": (
        "sale_id",
        "org_id",
        "ndc",
        "drug_name",
        "data_source",
        "brand_flag",
        "pack_units",
        "total_mg",
        "wac",
        "transaction_date",
        "week_ending_date",
        "state",
        "specialty",
        "period_wk",
        "period_mo",
        "period_qtr",
        "wk_offset",
        "mo_offset",
    ),
}


def role_safe_schema(role: UserRole) -> dict[str, list[str]]:
    schema = {table: list(columns) for table, columns in ANALYTICS_SCHEMA.items()}
    if role != UserRole.EXEC:
        schema["sales"].remove("wac")
    return schema
