"""Local interest graph, reviewed application documents and networking helpers."""
from __future__ import annotations

from datetime import UTC, datetime
import json
import re
import sqlite3
from urllib.parse import quote_plus, urlparse

from pydantic import BaseModel, Field, field_validator


# A many-to-many navigation graph, not a qualification/degree eligibility gate.
FIELDS = {
    "Engineering": {
        "Electrical engineering": ("Hardware Engineer", "Electrical Engineer", "Embedded Software Engineer", "Machine Learning Engineer"),
        "Mechanical engineering": ("Mechanical Engineer", "Robotics Engineer", "Manufacturing Engineer"),
        "Software engineering": ("Software Engineer", "Backend Engineer", "Frontend Engineer", "Embedded Software Engineer", "Machine Learning Engineer"),
        "Robotics & systems": ("Robotics Engineer", "Controls Engineer", "Hardware Engineer", "Machine Learning Engineer"),
        "Civil & energy": ("Civil Engineer", "Energy Engineer", "Process Engineer"),
        "Aerospace & defense": ("Aerospace Engineer", "Avionics Engineer", "Systems Engineer", "Mechanical Engineer"),
        "Chemical & materials": ("Chemical Engineer", "Materials Scientist", "Process Engineer"),
    },
    "Data & AI": {
        "Machine learning": ("Machine Learning Engineer", "Applied Scientist", "Research Engineer", "Data Scientist"),
        "Data engineering": ("Data Engineer", "Analytics Engineer", "Backend Engineer"),
        "Data analysis": ("Data Analyst", "Data Scientist", "Business Intelligence Analyst"),
        "AI product & safety": ("AI Product Manager", "AI Safety Researcher", "Machine Learning Engineer"),
    },
    "Finance": {
        "Private equity": ("Private Equity Analyst", "Investment Analyst"),
        "Investment banking": ("Investment Banking Analyst", "M&A Analyst"),
        "Venture capital": ("Venture Capital Analyst", "Investment Analyst"),
        "Markets & quantitative finance": ("Quantitative Researcher", "Quantitative Developer", "Risk Analyst", "Machine Learning Engineer"),
        "Corporate finance": ("Financial Analyst", "FP&A Analyst", "Treasury Analyst"),
        "Accounting & audit": ("Auditor", "Accountant", "Financial Controller"),
        "Fintech & payments": ("Fintech Analyst", "Payments Product Manager", "Risk Analyst"),
    },
    "Marketing": {
        "Growth & performance": ("Growth Marketer", "Performance Marketing Analyst", "Marketing Analyst"),
        "Brand & content": ("Brand Strategist", "Content Marketer", "Product Marketing Manager"),
        "Research & communications": ("Market Research Analyst", "Communications Specialist"),
    },
    "Business": {
        "Strategy & consulting": ("Strategy Analyst", "Business Analyst", "Management Consultant"),
        "Product & operations": ("Product Manager", "Operations Analyst", "Business Analyst"),
        "Sales & partnerships": ("Business Development Representative", "Account Executive", "Partnerships Associate"),
        "People & HR": ("HR Associate", "Recruiter", "People Operations Analyst"),
        "Supply chain & logistics": ("Supply Chain Analyst", "Logistics Coordinator", "Procurement Analyst"),
    },
    "Science & research": {
        "Computer science & AI": ("Machine Learning Engineer", "Research Engineer", "Applied Scientist", "Data Scientist"),
        "Neuroscience & Neuro-X": ("Machine Learning Engineer", "Neurotechnology Engineer", "Research Engineer"),
        "Economics & statistics": ("Economist", "Data Scientist", "Quantitative Researcher", "Machine Learning Engineer"),
        "Life sciences": ("Bioinformatics Scientist", "Research Scientist", "Biomedical Engineer"),
        "Physics & quantum": ("Research Scientist", "Quantum Engineer", "Data Scientist"),
    },
    "Healthcare & biotech": {
        "Biotech & pharma": ("Biomedical Engineer", "Research Scientist", "Clinical Data Analyst"),
        "Clinical & care": ("Clinical Research Coordinator", "Medical Affairs Associate", "Registered Nurse"),
        "Public health": ("Public Health Analyst", "Epidemiologist", "Health Policy Analyst"),
    },
    "Law & policy": {
        "Legal": ("Paralegal", "Legal Associate", "Contracts Analyst"),
        "Compliance & regulatory": ("Compliance Analyst", "Regulatory Affairs Associate", "Risk Analyst"),
        "Public policy": ("Policy Analyst", "Government Affairs Associate", "Economist"),
    },
    "Media & creative": {
        "Games & interactive": ("Game Designer", "Gameplay Engineer", "Technical Artist"),
        "Film & content": ("Video Editor", "Content Producer", "Content Marketer"),
        "Music & audio": ("Audio Engineer", "Music Producer", "Sound Designer"),
    },
    "Sustainability & climate": {
        "Climate tech": ("Climate Analyst", "Energy Engineer", "Sustainability Consultant"),
        "Environment": ("Environmental Scientist", "ESG Analyst", "Conservation Scientist"),
    },
    "Education": {
        "Teaching & academia": ("Teacher", "Teaching Assistant", "Research Assistant"),
        "EdTech & learning design": ("Instructional Designer", "EdTech Product Manager", "Learning Experience Designer"),
    },
    "Design": {
        "Product & experience": ("Product Designer", "UX Researcher", "UX Designer"),
        "Visual & brand": ("Visual Designer", "Brand Designer", "Graphic Designer"),
        "Industrial design": ("Industrial Designer", "Hardware Engineer", "CAD Designer"),
    },
    "Other": {"Explore a different path": ()},
}


def suggested_roles(subfields: list[str]) -> list[str]:
    return sorted({role for branches in FIELDS.values() for field, roles in branches.items()
                   if field in subfields for role in roles})


class Interests(BaseModel):
    fields: list[str] = Field(default_factory=list, max_length=15)
    subfields: list[str] = Field(default_factory=list, max_length=30)
    roles: list[str] = Field(min_length=1, max_length=20)

    @field_validator("fields", "subfields", "roles")
    @classmethod
    def clean(cls, values):
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("Choose names between 1 and 100 characters")
        return list(dict.fromkeys(value.strip() for value in values))


class HubStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS career_interests (
                    track_id TEXT PRIMARY KEY REFERENCES career_workspaces(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS career_role_pages (
                    track_id TEXT NOT NULL REFERENCES career_workspaces(id) ON DELETE CASCADE,
                    role_key TEXT NOT NULL,
                    thread_id TEXT NOT NULL REFERENCES career_threads(id) ON DELETE CASCADE,
                    PRIMARY KEY(track_id, role_key)
                );
                CREATE TABLE IF NOT EXISTS career_documents (
                    thread_id TEXT PRIMARY KEY REFERENCES career_threads(id) ON DELETE CASCADE,
                    letter TEXT NOT NULL DEFAULT '', resume TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def owned(db, track, thread=None):
        row = (db.execute("SELECT 1 FROM career_threads WHERE id=? AND workspace_id=?", (thread, track)).fetchone()
               if thread else db.execute("SELECT 1 FROM career_workspaces WHERE id=?", (track,)).fetchone())
        if not row:
            raise ValueError("Career workspace not found")

    def interests(self, track):
        with self.connect() as db:
            self.owned(db, track)
            row = db.execute("SELECT payload FROM career_interests WHERE track_id=?", (track,)).fetchone()
        return Interests.model_validate_json(row[0]) if row else None

    def save_interests(self, track, interests):
        interests = Interests.model_validate(interests.model_dump())
        with self.connect() as db:
            self.owned(db, track)
            db.execute("INSERT OR REPLACE INTO career_interests VALUES (?,?)", (track, interests.model_dump_json()))

    def role_page(self, workspaces, track, role):
        role = role.strip()
        if not role or len(role) > 100:
            raise ValueError("Choose a role between 1 and 100 characters")
        with self.connect() as db:
            self.owned(db, track)
            row = db.execute("SELECT thread_id FROM career_role_pages WHERE track_id=? AND role_key=?", (track, role.casefold())).fetchone()
            if row:
                self.owned(db, track, row[0])
                return row[0]
        thread = workspaces.create_thread(track, role, {**workspaces.shared_profile(), "job_title": role})
        with self.connect() as db:
            db.execute("INSERT INTO career_role_pages VALUES (?,?,?)", (track, role.casefold(), thread))
        return thread

    def documents(self, track, thread):
        with self.connect() as db:
            self.owned(db, track, thread)
            row = db.execute("SELECT letter,resume FROM career_documents WHERE thread_id=?", (thread,)).fetchone()
        return dict(row) if row else {"letter": "", "resume": ""}

    def save_documents(self, track, thread, *, letter, resume):
        if not all(isinstance(value, str) and len(value) <= 100_000 for value in (letter, resume)):
            raise ValueError("Each document is limited to 100,000 characters")
        with self.connect() as db:
            self.owned(db, track, thread)
            db.execute("INSERT OR REPLACE INTO career_documents VALUES (?,?,?,?)",
                       (thread, letter, resume, datetime.now(UTC).isoformat()))


def draft_documents(cv: str, title: str, company: str, skills: list[str], *, sender_name: str = "") -> tuple[str, str]:
    """No provider call: preserve source CV verbatim and add labelled targeting text."""
    if not cv.strip():
        raise ValueError("Add your background or a CV first; we cannot invent your experience")
    relevant = ", ".join(skills) or "[add a role-relevant fact you can substantiate]"
    resume = f"TARGET: {title} — {company}\nRelevant evidence to review: {relevant}\n\n{cv.strip()}"
    signature = sender_name.strip() or "[Your name]"
    letter = (f"Dear {company} hiring team,\n\nI would like to apply for the {title} role.\n\n"
              f"The supplied CV contains the following role-relevant evidence: {relevant}. "
              "[Replace this sentence with one specific example of your contribution and its outcome.]\n\n"
              "[Explain why this company's work and this role interest you.]\n\n"
              "Thank you for considering my application. I would welcome the chance to discuss my work.\n\n"
              f"{signature}")
    return resume, letter


def contact_searches(company: str, title: str):
    specialties = ("Hardware Engineering Manager", "Technical Recruiter", "Hardware Team Lead") if "hardware" in title.casefold() else (f"{title} team lead", "Recruiter", "Hiring manager")
    return [(role, "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(f"{company} {role}")) for role in specialties]


def infer_email(name: str, domain: str, pattern: str, source_url: str) -> str:
    """A user-supplied public naming pattern yields a hypothesis, never a verified email."""
    parts = re.findall(r"[a-z]+", name.casefold())
    domain = domain.strip().casefold()
    if len(parts) < 2 or not re.fullmatch(r"(?=.{3,253}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", domain):
        raise ValueError("Provide a first and last name and a valid company domain")
    source = urlparse(source_url)
    if source.scheme != "https" or not source.hostname or source.username or source.password:
        raise ValueError("Add a public HTTPS source for the observed company pattern")
    templates = {"first.last": f"{parts[0]}.{parts[-1]}", "flast": f"{parts[0][0]}{parts[-1]}", "first": parts[0]}
    if pattern not in templates:
        raise ValueError("Choose a supported pattern")
    return templates[pattern] + "@" + domain
