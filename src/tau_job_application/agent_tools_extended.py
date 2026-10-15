"""Typed Tau tools for the YC directory and work-eligibility specialists.

These are narrow adapters over deterministic domain functions and local
stores. The directory search tool reads only the locally stored snapshot; a
network refresh happens only through the explicit ``refresh_yc_directory``
tool, which fetches the single fixed yc-oss endpoint. Canonical state changes
always go through the stores, never through model-generated prose.
"""
from __future__ import annotations

from collections.abc import Mapping

from tau_agent import AgentTool, AgentToolResult, TextContent
from tau_agent.types import JSONValue

from tau_job_application.company_catalog import CatalogCompany, CompanyCatalogStore
from tau_job_application.eligibility import (
    ResidencyProfile,
    ResidencyStore,
    eligibility_checklist,
)
from tau_job_application.yc_directory import (
    YC_STATUSES,
    YCDirectoryStore,
    YCFilters,
    fetch_yc_directory,
)


def _ok(message: str, details: dict) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=message)], details={"ok": True, **details})


def _error(exc: Exception) -> AgentToolResult:
    return AgentToolResult(content=f"Invalid tool input: {exc}", details={"ok": False, "error": str(exc)})


def _cancelled(signal) -> AgentToolResult | None:
    if signal is not None and signal.is_cancelled():
        return AgentToolResult(content="Tool call cancelled", details={"ok": False, "cancelled": True})
    return None


def _strings(arguments: Mapping[str, JSONValue], key: str) -> tuple[str, ...]:
    value = arguments.get(key, ())
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} must be a list of strings")
    return tuple(str(item) for item in value)


def create_company_scout_tools(*, yc_store: YCDirectoryStore, catalog_store: CompanyCatalogStore) -> list[AgentTool]:
    """Read/search the local YC snapshot; save reviewed picks to the catalogue."""

    async def execute_search(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
        del tool_call_id, on_update
        if cancelled := _cancelled(signal):
            return cancelled
        try:
            filters = YCFilters(
                statuses=_strings(arguments, "statuses"),
                hiring_only=bool(arguments.get("hiring_only", False)),
                top_only=bool(arguments.get("top_only", False)),
                batches=_strings(arguments, "batches"),
                industries=_strings(arguments, "industries"),
                regions=_strings(arguments, "regions"),
                query=str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 25)),
            )
            matches = yc_store.search(filters)
            snapshot = yc_store.snapshot()
        except (KeyError, TypeError, ValueError) as exc:
            return _error(exc)
        if snapshot is None:
            return _ok("The local YC directory snapshot is empty. Ask the user before calling refresh_yc_directory.", {"companies": [], "snapshot": None})
        payload = [
            {"slug": c.slug, "name": c.name, "status": c.status, "batch": c.batch,
             "is_hiring": c.is_hiring, "industries": list(c.industries), "regions": list(c.regions),
             "team_size": c.team_size, "one_liner": c.one_liner, "directory_url": c.directory_url}
            for c in matches
        ]
        return _ok(
            f"Found {len(payload)} companie(s) in the local YC snapshot (refreshed {snapshot['refreshed_at']}).",
            {"companies": payload, "snapshot": snapshot},
        )

    async def execute_refresh(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
        del tool_call_id, arguments, on_update
        if cancelled := _cancelled(signal):
            return cancelled
        try:
            companies = fetch_yc_directory()
            count = yc_store.refresh(companies)
        except (RuntimeError, ValueError) as exc:
            return _error(exc)
        return _ok(f"Refreshed the local YC directory snapshot with {count} public records from the yc-oss mirror.", {"record_count": count})

    async def execute_save(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
        del tool_call_id, on_update
        if cancelled := _cancelled(signal):
            return cancelled
        try:
            wanted = set(_strings(arguments, "slugs"))
            if not wanted or len(wanted) > 100:
                raise ValueError("Provide between 1 and 100 company slugs")
            by_slug = {company.slug: company for company in yc_store.companies()}
            missing = sorted(wanted - set(by_slug))
            records = [
                CatalogCompany(
                    source="YC community API", source_key=company.slug,
                    source_url=company.directory_url, name=company.name, company_type="Startup",
                    website=company.website, locations=company.locations,
                    industry=company.industries[0] if company.industries else None,
                    funding_stage=company.stage or "Unknown",
                    hiring=company.is_hiring, yc_batch=company.batch, summary=company.one_liner,
                )
                for slug, company in by_slug.items() if slug in wanted
            ]
            imported = catalog_store.import_companies(records) if records else 0
        except (TypeError, ValueError) as exc:
            return _error(exc)
        message = f"Saved {imported} companie(s) as local research leads in the company database."
        if missing:
            message += f" Not found in the snapshot: {', '.join(missing)}."
        return _ok(message, {"imported": imported, "missing_slugs": missing})

    search_schema = {
        "type": "object",
        "properties": {
            "statuses": {"type": "array", "items": {"type": "string", "enum": list(YC_STATUSES)}},
            "hiring_only": {"type": "boolean"},
            "top_only": {"type": "boolean"},
            "batches": {"type": "array", "items": {"type": "string"}},
            "industries": {"type": "array", "items": {"type": "string"}},
            "regions": {"type": "array", "items": {"type": "string"}},
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "additionalProperties": False,
    }
    return [
        AgentTool(
            name="search_yc_directory", label="Search local YC directory",
            description="Filter the locally stored YC company snapshot by status (Active/Acquired/Public/Inactive), hiring flag, batch, industry, region, team size, or text query. Reads local data only.",
            parameters=search_schema, execute_fn=execute_search,
        ),
        AgentTool(
            name="refresh_yc_directory", label="Refresh YC directory snapshot",
            description="Fetch the public yc-oss company directory once and replace the local snapshot. Use only when the user asks for fresh data; the snapshot may be hours old and the hiring flag is not a vacancy guarantee.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            execute_fn=execute_refresh,
        ),
        AgentTool(
            name="save_yc_companies_to_catalog", label="Save YC companies to database",
            description="Save selected YC companies (by slug) as local research leads in the company database. Never implies an open vacancy.",
            parameters={
                "type": "object",
                "properties": {"slugs": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100}},
                "required": ["slugs"], "additionalProperties": False,
            },
            execute_fn=execute_save,
        ),
    ]


def create_eligibility_tools(*, residency_store: ResidencyStore, workspace_id: str) -> list[AgentTool]:
    """Store the self-declared residency profile and build rule-based checklists."""

    async def execute_save_profile(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
        del tool_call_id, on_update
        if cancelled := _cancelled(signal):
            return cancelled
        try:
            profile = ResidencyProfile(
                citizenships=_strings(arguments, "citizenships"),
                residence_country=str(arguments["residence_country"]),
                work_permits=_strings(arguments, "work_permits"),
            )
            residency_store.save(workspace_id, profile)
        except (KeyError, TypeError, ValueError) as exc:
            return _error(exc)
        return _ok(
            f"Saved residency profile: citizen of {', '.join(profile.citizenships)}; resident in {profile.residence_country}.",
            {"profile": profile.model_dump(mode="json")},
        )

    async def execute_get_profile(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
        del tool_call_id, arguments, on_update
        if cancelled := _cancelled(signal):
            return cancelled
        profile = residency_store.get(workspace_id)
        if profile is None:
            return _ok("No residency profile saved yet. Ask the user for their citizenship(s), country of residence, and any existing work permits.", {"profile": None})
        return _ok("Current residency profile.", {"profile": profile.model_dump(mode="json")})

    async def execute_checklist(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
        del tool_call_id, on_update
        if cancelled := _cancelled(signal):
            return cancelled
        profile = residency_store.get(workspace_id)
        if profile is None:
            return _ok("No residency profile saved yet. Ask the user for their citizenship(s), country of residence, and existing work permits before building a checklist.", {"result": None})
        try:
            result = eligibility_checklist(profile, str(arguments["job_country"]))
        except (KeyError, TypeError, ValueError) as exc:
            return _error(exc)
        return _ok(
            f"Eligibility pathway for {result.job_country}: {result.pathway}. Remind the user this is not legal advice.",
            {"result": result.model_dump(mode="json")},
        )

    return [
        AgentTool(
            name="save_residency_profile", label="Save residency profile",
            description="Save the user's self-declared citizenships, country of residence, and countries where they already hold a work permit. Use full English country names.",
            parameters={
                "type": "object",
                "properties": {
                    "citizenships": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "residence_country": {"type": "string"},
                    "work_permits": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["citizenships", "residence_country"], "additionalProperties": False,
            },
            execute_fn=execute_save_profile,
        ),
        AgentTool(
            name="get_residency_profile", label="Get residency profile",
            description="Read the saved self-declared residency profile for this career track.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            execute_fn=execute_get_profile,
        ),
        AgentTool(
            name="build_eligibility_checklist", label="Build eligibility checklist",
            description="Build the rule-based document checklist for applying in a job country, based on the saved residency profile. Output is a preparation aid, never legal advice.",
            parameters={
                "type": "object",
                "properties": {"job_country": {"type": "string"}},
                "required": ["job_country"], "additionalProperties": False,
            },
            execute_fn=execute_checklist,
        ),
    ]
