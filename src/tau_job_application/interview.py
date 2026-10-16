"""Structured interview practice with local, explainable feedback.

Difficulty is progressive (the Zenply training pillar): every three saved
rehearsals scored 75+ raise the level, from fundamentals to
cross-examination. Levels are derived deterministically from the workspace's
own attempt history — never from model judgement.
"""

from __future__ import annotations

import re
from tau_job_application.models import CandidateProfile, InterviewFeedback, InterviewQuestion, JobPosting

MAX_LEVEL = 5
LEVEL_NAMES = {
    1: "Fundamentals",
    2: "Role specifics",
    3: "Trade-offs & design",
    4: "Failure & ambiguity",
    5: "Cross-examination",
}
LEVEL_PASS_SCORE = 75
LEVEL_PASS_COUNT = 3


def difficulty_level(attempts: list[dict]) -> int:
    """1 + one level per three rehearsals at 75+; capped at MAX_LEVEL."""

    passed = sum(1 for attempt in attempts if isinstance(attempt.get("score"), int) and attempt["score"] >= LEVEL_PASS_SCORE)
    return min(MAX_LEVEL, 1 + passed // LEVEL_PASS_COUNT)


def level_progress(attempts: list[dict]) -> tuple[int, int]:
    """(passed toward next level, needed) for the progress display."""

    passed = sum(1 for attempt in attempts if isinstance(attempt.get("score"), int) and attempt["score"] >= LEVEL_PASS_SCORE)
    if difficulty_level(attempts) >= MAX_LEVEL:
        return LEVEL_PASS_COUNT, LEVEL_PASS_COUNT
    return passed % LEVEL_PASS_COUNT, LEVEL_PASS_COUNT


def _level_twist(level: int, skill: str, job_title: str) -> str:
    if level == 2:
        return f"Go deeper on {skill}: design a small component of a {job_title} system that relies on it. What are the interfaces, invariants, and limits?"
    if level == 3:
        return f"Defend a design choice involving {skill}: what alternative did you reject, what would you measure, and when would the simpler option win?"
    if level == 4:
        return f"Tell me about a time something involving {skill} failed or requirements changed mid-way. How did you diagnose it, and what did you change?"
    if level >= 5:
        return f"Cross-examination on {skill}: justify every assumption in your approach. Why is it not over-engineered? What are you still uncertain about?"
    return f"Walk me through how you have used {skill}, or how you would approach a small task requiring it."


def build_interview_questions(candidate: CandidateProfile, job: JobPosting, *, level: int = 1) -> list[InterviewQuestion]:
    if not 1 <= level <= MAX_LEVEL:
        raise ValueError(f"Interview level must be between 1 and {MAX_LEVEL}")
    questions = [
        InterviewQuestion(id="motivation", category="motivation", question=f"Why this {job.title} role at {job.company}, and why now?", what_good_evidence_looks_like=["Specific company/role research", "A truthful connection to candidate experience", "A learning goal without overstating ability"]),
        InterviewQuestion(id="impact", category="behavioral", question="Tell me about a project or experience where you improved something. What was your contribution and how did you know it worked?", what_good_evidence_looks_like=["Situation and responsibility", "Specific actions", "Observable result or honest limitation", "Reflection"]),
    ]
    if level >= 4:
        questions.append(InterviewQuestion(
            id="ambiguity", category="behavioral",
            question="Describe a situation where the goal was unclear or kept changing. What did you decide, and how did you make progress without perfect information?",
            what_good_evidence_looks_like=["Explicit assumptions", "Small reversible steps", "Honest uncertainty", "A checkpoint with stakeholders"],
        ))
    for index, requirement in enumerate(job.requirements[:5], start=1):
        if requirement.required:
            questions.append(InterviewQuestion(
                id=f"technical-{index}", category="technical",
                question=_level_twist(level, requirement.skill, job.title),
                what_good_evidence_looks_like=["Clear assumptions", "Concrete steps", "Validation or testing", "Trade-offs and limits"],
            ))
    return questions


def evaluate_answer(question: InterviewQuestion, answer: str) -> InterviewFeedback:
    text = answer.strip()
    lower = text.casefold()
    strengths = []
    missing = []
    checks = {
        "context": ("context", "situation", "project", "team", "user"),
        "action": ("i built", "i implemented", "i analysed", "i analyzed", "i decided", "i wrote"),
        "validation": ("test", "measure", "metric", "result", "verified", "feedback"),
        "reflection": ("learned", "trade-off", "would", "improve", "limitation"),
    }
    for label, terms in checks.items():
        if any(term in lower for term in terms):
            strengths.append(f"Includes {label}.")
        else:
            missing.append(f"Add {label}.")
    if len(text.split()) < 35:
        missing.append("Give enough concrete detail for an interviewer to assess your reasoning.")
    if not text:
        return InterviewFeedback(question_id=question.id, strengths=[], missing=["Provide an answer first."], follow_up="What is one truthful example you could use?", score=0)
    score = min(100, max(20, 25 * len(strengths) + (10 if len(text.split()) >= 35 else 0)))
    follow_up = "What was the observable result, and what would you change next time?" if "validation" in " ".join(missing) else "What trade-off did you consider?"
    return InterviewFeedback(question_id=question.id, strengths=strengths, missing=missing, follow_up=follow_up, score=score)


def transcribe_openai_audio(audio_bytes: bytes, filename: str, api_key: str, model: str = "gpt-4o-mini-transcribe") -> str:
    """Optional explicit transcription. Audio is sent only after the user presses transcribe."""
    from urllib.request import Request, urlopen
    import json
    import uuid
    boundary = f"----JobAssistant{uuid.uuid4().hex}"
    fields = [("model", model, None), ("file", filename, audio_bytes)]
    body = bytearray()
    for name, value, binary in fields:
        body.extend(f"--{boundary}\r\n".encode())
        if binary is None:
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        else:
            body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{value}"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
            body.extend(binary)
            body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request = Request("https://api.openai.com/v1/audio/transcriptions", data=bytes(body), method="POST", headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urlopen(request, timeout=45) as response:  # noqa: S310 - fixed OpenAI endpoint
        return json.loads(response.read().decode())["text"]
