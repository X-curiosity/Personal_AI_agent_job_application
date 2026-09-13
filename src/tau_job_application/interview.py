"""Structured interview practice with local, explainable feedback."""

from __future__ import annotations

import re
from tau_job_application.models import CandidateProfile, InterviewFeedback, InterviewQuestion, JobPosting


def build_interview_questions(candidate: CandidateProfile, job: JobPosting) -> list[InterviewQuestion]:
    questions = [
        InterviewQuestion(id="motivation", category="motivation", question=f"Why this {job.title} role at {job.company}, and why now?", what_good_evidence_looks_like=["Specific company/role research", "A truthful connection to candidate experience", "A learning goal without overstating ability"]),
        InterviewQuestion(id="impact", category="behavioral", question="Tell me about a project or experience where you improved something. What was your contribution and how did you know it worked?", what_good_evidence_looks_like=["Situation and responsibility", "Specific actions", "Observable result or honest limitation", "Reflection"]),
    ]
    for index, requirement in enumerate(job.requirements[:5], start=1):
        if requirement.required:
            questions.append(InterviewQuestion(
                id=f"technical-{index}", category="technical",
                question=f"Walk me through how you have used {requirement.skill}, or how you would approach a small task requiring it.",
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
