"""CLI entry points for local analysis, optional agent use, and the local UI."""

import argparse
import asyncio
from pathlib import Path
import subprocess
import sys

from tau_job_application.parsing import load_document
from tau_job_application.pipeline import analyze_files, render_markdown

def _project_root() -> Path:
    """Find fixtures when installed as either editable or regular package."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "fixtures").is_dir():
            return directory
    return Path.cwd()


PROJECT_ROOT = _project_root()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence-first job-readiness assistant")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Run the deterministic synthetic demo")
    analyze = commands.add_parser("analyze", help="Analyze two local CV/job documents")
    analyze.add_argument("candidate", type=Path)
    analyze.add_argument("job", type=Path)
    agent = commands.add_parser("agent", help="Run the optional Tau agent (requires model credentials)")
    agent.add_argument("candidate", type=Path)
    agent.add_argument("job", type=Path)
    team = commands.add_parser("agent-team", help="Route one request through the optional multi-agent team (requires model credentials)")
    team.add_argument("request", type=str)
    team.add_argument("--specialist", choices=["company_scout", "eligibility_advisor", "application_prep"], default=None)
    commands.add_parser("refresh-data", help="Refresh company snapshots and rebuild the actively-hiring index (used by the schedule)")
    commands.add_parser("ui", help="Launch the local Streamlit application")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "demo":
        print(render_markdown(analyze_files(PROJECT_ROOT / "fixtures" / "candidate.txt", PROJECT_ROOT / "fixtures" / "job.txt")))
    elif args.command == "analyze":
        print(render_markdown(analyze_files(args.candidate, args.job)))
    elif args.command == "ui":
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py"))], check=True)
    elif args.command == "agent-team":
        asyncio.run(_run_agent_team(args.request, specialist=args.specialist))
    elif args.command == "refresh-data":
        _refresh_data()
    else:
        asyncio.run(_run_agent(args.candidate, args.job))


async def _run_agent(candidate_path: Path, job_path: Path) -> None:
    candidate_text, job_text = load_document(candidate_path), load_document(job_path)
    prompt = "Use tools to analyse this candidate and job. Do not add unsupported facts.\n\nCANDIDATE\n" + candidate_text + "\n\nJOB\n" + job_text
    # Import Tau only for the optional model-backed command. The deterministic CLI stays dependency-light.
    from tau_job_application.agent import build_agent

    async for event in build_agent().prompt(prompt):
        print(event)


def _refresh_data() -> None:
    """Scheduled refresh: snapshots + hiring index. Failures keep previous data."""

    from tau_job_application.capital_atlas import fetch_atlas_companies
    from tau_job_application.hiring_index import refresh_all_data
    from tau_job_application.sources import fetch_public_board_openings
    from tau_job_application.yc_directory import fetch_yc_directory

    database = PROJECT_ROOT / ".job_assistant" / "assistant.sqlite"
    summary = refresh_all_data(
        database,
        yc_fetcher=fetch_yc_directory,
        atlas_fetcher=fetch_atlas_companies,
        openings_fetcher=fetch_public_board_openings,
    )
    role_markets = summary.get("role_markets", {})
    print(
        f"refresh-data: yc={summary.get('yc_records', 'kept')} "
        f"atlas={summary.get('atlas_records', 'kept')} "
        f"indexed={summary.get('indexed', 0)} live={summary.get('live', 0)} "
        f"role-boards={role_markets.get('refreshed', 0)} refreshed, {role_markets.get('kept', 0)} kept"
    )
    for error in summary["errors"]:
        print(f"  warning: {error}")


async def _run_agent_team(request: str, *, specialist: str | None = None) -> None:
    """One bounded specialist run; routing, budget, and trace stay visible."""

    from tau_job_application.agents import TeamCoordinator, TeamDependencies
    from tau_job_application.agent import build_agent  # validates credentials early
    from tau_job_application.company_catalog import CompanyCatalogStore
    from tau_job_application.eligibility import ResidencyStore
    from tau_job_application.yc_directory import YCDirectoryStore

    harness = build_agent()  # raises unless OPENAI_API_KEY and MODEL_NAME are set
    database = PROJECT_ROOT / ".job_assistant" / "assistant.sqlite"
    coordinator = TeamCoordinator(
        provider=harness.config.provider, model=harness.config.model,
        deps=TeamDependencies(
            yc_store=YCDirectoryStore(database),
            catalog_store=CompanyCatalogStore(database),
            residency_store=ResidencyStore(database),
            workspace_id="cli",
        ),
    )
    result = await coordinator.run(request, agent_key=specialist)
    print(f"# {result.agent_name} — {result.routing.reason}")
    for call in result.tool_trace:
        status = "ok" if call.ok else ("error" if call.ok is False else "pending")
        print(f"- [{status}] {call.tool_name} {call.arguments}")
    if result.blocked_tool_calls:
        print(f"- {result.blocked_tool_calls} tool call(s) blocked by the run budget")
    if result.error:
        print(f"ERROR: {result.error}")
    print(result.text)
