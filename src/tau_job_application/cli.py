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
    else:
        asyncio.run(_run_agent(args.candidate, args.job))


async def _run_agent(candidate_path: Path, job_path: Path) -> None:
    candidate_text, job_text = load_document(candidate_path), load_document(job_path)
    prompt = "Use tools to analyse this candidate and job. Do not add unsupported facts.\n\nCANDIDATE\n" + candidate_text + "\n\nJOB\n" + job_text
    # Import Tau only for the optional model-backed command. The deterministic CLI stays dependency-light.
    from tau_job_application.agent import build_agent

    async for event in build_agent().prompt(prompt):
        print(event)
