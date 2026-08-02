"""Small CLI for the deterministic template and optional Tau spike."""

import argparse
import asyncio
from pathlib import Path

from tau_job_application.agent import build_agent
from tau_job_application.parsing import load_document
from tau_job_application.pipeline import analyze_files, render_markdown


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tau job-application assistant template")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("demo", help="Run the deterministic synthetic demo")

    analyze = subparsers.add_parser("analyze", help="Analyze two local documents")
    analyze.add_argument("candidate", type=Path)
    analyze.add_argument("job", type=Path)

    agent = subparsers.add_parser("agent", help="Run the optional Tau agent spike")
    agent.add_argument("candidate", type=Path)
    agent.add_argument("job", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "demo":
        result = analyze_files(
            PROJECT_ROOT / "fixtures" / "candidate.txt",
            PROJECT_ROOT / "fixtures" / "job.txt",
        )
        print(render_markdown(result))
        return
    if args.command == "analyze":
        print(render_markdown(analyze_files(args.candidate, args.job)))
        return
    asyncio.run(_run_agent(args.candidate, args.job))


async def _run_agent(candidate_path: Path, job_path: Path) -> None:
    candidate_text = load_document(candidate_path)
    job_text = load_document(job_path)
    prompt = (
        "Use the analysis tool with the candidate and job data below. Explain the "
        "result without adding unsupported facts.\n\n"
        f"CANDIDATE DATA\n{candidate_text}\n\nJOB DATA\n{job_text}"
    )
    harness = build_agent()
    async for event in harness.prompt(prompt):
        # TODO: replace repr(event) with an event-specific CLI renderer.
        print(event)
