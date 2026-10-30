"""CLI entry points for local analysis, optional agent use, and the local UI."""

import argparse
import asyncio
import json
from pathlib import Path
import re
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
    auto = commands.add_parser("auto-apply", help="Fill and review one application in a visible local browser without an LLM")
    auto.add_argument("candidate", type=Path, help="Local CV to attach")
    auto.add_argument("job_url", help="Public HTTPS vacancy URL")
    auto.add_argument("--application-id", required=True, help="Unique ID for this reviewed application")
    auto.add_argument("--full-name", required=True)
    auto.add_argument("--email", required=True)
    auto.add_argument("--phone", default="")
    auto.add_argument("--location", default="")
    auto.add_argument("--skills", default="")
    auto.add_argument("--custom-answers", default="{}", help="JSON object of exact-label string/boolean answers")
    auto.add_argument("--form-selector", default="form")
    auto.add_argument("--allow-json", action="store_true")
    folders = commands.add_parser("folders", help="Manage role folders and run the deterministic folder agent")
    folder_commands = folders.add_subparsers(dest="folder_command", required=True)
    folder_commands.add_parser("list", help="List role folders")
    create = folder_commands.add_parser("create", help="Create a role folder")
    create.add_argument("--name", required=True)
    create.add_argument("--roles", default="", help="Comma-separated role keywords, e.g. 'ml engineer, machine learning'")
    create.add_argument("--region", default="Any")
    create.add_argument("--type", dest="company_type", default="any", choices=["any", "startup", "public", "private"])
    create.add_argument("--sector", default="")
    create.add_argument("--sub-sector", default="")
    create.add_argument("--cv", type=Path, default=None)
    create.add_argument("--letter", type=Path, default=None)
    docs = folder_commands.add_parser("documents", help="Attach a CV and letter to an existing folder")
    docs.add_argument("folder_id", type=int)
    docs.add_argument("--cv", type=Path, default=None)
    docs.add_argument("--letter", type=Path, default=None)
    run = folder_commands.add_parser("run", help="Run the folder agent (all folders, or one with --folder)")
    run.add_argument("--folder", type=int, default=None)
    run.add_argument("--pdf-dir", type=Path, default=Path.cwd(), help="Directory to write one PDF project description per matched role")
    show = folder_commands.add_parser("show", help="Show a folder's latest matches")
    show.add_argument("folder_id", type=int)
    delete = folder_commands.add_parser("delete", help="Delete a folder")
    delete.add_argument("folder_id", type=int)
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
    elif args.command == "auto-apply":
        _auto_apply(args)
    elif args.command == "folders":
        _folders(args)
    else:
        asyncio.run(_run_agent(args.candidate, args.job))


def _auto_apply(args: argparse.Namespace) -> None:
    """Run one deterministic application; approval is interactive every time."""
    from tau_job_application.rule_based_apply import RuleBasedApplyConfig, run, validate_custom_answers
    try:
        custom = validate_custom_answers(json.loads(args.custom_answers))
    except (json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"Invalid --custom-answers: {exc}") from exc

    def approve(fingerprint: str, details: dict) -> bool:
        print("Submission paused. Review the visible browser form and target:", dict(details))
        return input(f"Type SUBMIT {fingerprint[:12]} to submit once: ").strip() == f"SUBMIT {fingerprint[:12]}"

    outcome = run(RuleBasedApplyConfig(
        job_url=args.job_url, application_id=args.application_id, form_selector=args.form_selector,
        full_name=args.full_name, email=args.email, phone=args.phone, location=args.location,
        skills=args.skills, custom_answers=custom, cv_file_path=str(args.candidate), cv_required=True,
        allow_json_submission=args.allow_json,
    ), approve_submit=approve)
    print(f"Auto-apply outcome: {outcome.status} — {outcome.reason}")
    if outcome.status != "submitted":
        raise SystemExit(1)


def _mime_for(path: Path) -> str:
    return {".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain", ".md": "text/markdown"}.get(path.suffix.casefold(), "text/plain")


def _attach_documents(store, folder_id: int, cv: Path | None, letter: Path | None) -> None:
    cv_bytes = cv_name = cv_mime = None
    if cv:
        cv_bytes, cv_name, cv_mime = cv.read_bytes(), cv.name, _mime_for(cv)
    letter_text = letter.read_text(encoding="utf-8") if letter else None
    store.set_documents(folder_id, cv_bytes, cv_name, cv_mime, letter_text)
    print(f"Attached {cv_name or 'no CV'} and {'letter' if letter_text else 'no letter'} to folder #{folder_id}")


def _write_project_pdf(pdf_dir: Path, folder_name: str, match: dict, letter_text: str | None) -> None:
    from tau_job_application.project_pdf import render_project_pdf
    pdf_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{match['company']}-{match['title']}".casefold()).strip("-")[:60] or "project"
    (pdf_dir / f"{slug}.pdf").write_bytes(render_project_pdf(match, folder_name, letter_text))
    print(f"  wrote {pdf_dir / (slug + '.pdf')}")


def _folders(args: argparse.Namespace) -> None:
    from tau_job_application.role_folders import RoleFolder, RoleFolderStore, load_companies, load_jobs, run_folder, run_all_folders
    store = RoleFolderStore()
    if args.folder_command == "list":
        folders = store.list()
        if not folders:
            print("No folders yet.")
            return
        for folder in folders:
            print(f"[{folder['id']}] {folder['name']} — region={folder['region']} type={folder['company_type']} roles={', '.join(folder['role_keywords'])}")
        return
    if args.folder_command == "create":
        folder = RoleFolder(name=args.name, role_keywords=[k.strip() for k in args.roles.split(",") if k.strip()],
                            sector=args.sector, sub_sector=args.sub_sector, region=args.region, company_type=args.company_type)
        folder_id = store.create(folder)
        print(f"Created folder #{folder_id}: {folder.name}")
        if args.cv or args.letter:
            _attach_documents(store, folder_id, args.cv, args.letter)
        return
    if args.folder_command == "documents":
        _attach_documents(store, args.folder_id, args.cv, args.letter)
        return
    if args.folder_command == "run":
        jobs, companies = load_jobs(), load_companies()
        if args.folder is not None:
            folder_row = store.get(args.folder)
            if not folder_row:
                raise SystemExit(f"No folder #{args.folder}")
            folder = RoleFolder(name=folder_row["name"], role_keywords=folder_row["role_keywords"], sector=folder_row["sector"],
                                sub_sector=folder_row["sub_sector"], region=folder_row["region"], company_type=folder_row["company_type"], id=folder_row["id"])
            matches = run_folder(store, folder, jobs, companies)
            store.replace_matches(folder.id, matches)
            summary = [{"id": folder.id, "name": folder.name, "matches": len(matches), "scores": [m.score for m in matches if m.score is not None]}]
        else:
            summary = run_all_folders(store, jobs, companies)["folders"]
        for row in summary:
            mean = round(sum(row["scores"]) / len(row["scores"])) if row["scores"] else None
            print(f"Folder #{row['id']} {row['name']}: {row['matches']} matching roles" + (f", mean score {mean}%" if mean is not None else ""))
        for row in summary:
            docs = store.documents(row["id"])
            for match in store.list_matches(row["id"]):
                _write_project_pdf(args.pdf_dir, row["name"], match, docs.get("letter_text"))
        return
    if args.folder_command == "show":
        folder = store.get(args.folder_id)
        if not folder:
            raise SystemExit(f"No folder #{args.folder_id}")
        print(f"Folder #{folder['id']}: {folder['name']} (region={folder['region']}, type={folder['company_type']})")
        matches = store.list_matches(args.folder_id)
        if not matches:
            print("No matches yet. Run 'folders run --folder <id>'.")
            return
        for match in matches:
            score = f"{match['score']}%" if match["score"] is not None else "no CV"
            print(f"  [{score}] {match['title']} @ {match['company']} ({match['area']}) — {match['url']}")
        return
    if args.folder_command == "delete":
        store.delete(args.folder_id)
        print(f"Deleted folder #{args.folder_id}")
        return


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
