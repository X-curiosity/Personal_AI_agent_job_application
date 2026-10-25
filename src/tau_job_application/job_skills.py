"""Canonical, deterministic skill vocabulary shared by adverts and CV matching."""
from __future__ import annotations

import re

SKILLS = ("Python", "C++", "C#", "Rust", "Go", "Java", "JavaScript", "TypeScript", "React", "SQL", "Kubernetes", "Docker", "Linux", "AWS", "GCP", "Terraform", "PyTorch", "TensorFlow", "CUDA", "Embedded", "FPGA", "ASIC", "Machine Learning", "LLM", "Data Engineering", "Distributed Systems", "Security", "Figma")


def extract_skills(text: str) -> list[str]:
    normalized = text.casefold()
    # Go is also a common English verb. Require source capitalization or the
    # Golang spelling and exclude frequent business/prose phrases.
    go_text = re.sub(r"(?i)go-to-market|as (?:you|we) go|to go from", "", text)
    return [
        skill for skill in SKILLS
        if (re.search(r"(?<![A-Za-z0-9])(?:Go|Golang)(?![A-Za-z0-9])", go_text) if skill == "Go" else re.search(rf"(?<![a-z0-9]){re.escape(skill.casefold())}(?![a-z0-9])", normalized))
    ]
