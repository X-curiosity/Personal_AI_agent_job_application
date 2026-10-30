"""Dependency-free PDF rendering for folder project descriptions.

Generates a minimal, valid PDF 1.4 document using the built-in Helvetica
fonts, so project descriptions open in any reader without adding a
reportlab/fpdf dependency. Text is limited to Latin-1 (non-Latin characters
are transliterated/replaced), which is sufficient for the generated English
project descriptions.
"""
from __future__ import annotations

import unicodedata


def _clean(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, size: int, width: int = 504) -> list[str]:
    """Approximate Helvetica character widths; conservative for readability."""
    max_chars = max(20, int(width / (size * 0.5)))
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def render_document(title: str, subtitle: str, sections: list[tuple[str, list[str]]],
                    accent: tuple[float, float, float] = (0.929, 0.416, 0.173)) -> bytes:
    objects: list[bytes] = []
    content: list[str] = []

    y = 756.0

    def emit(text: str, size: int, bold: bool, color: tuple[float, float, float] | None = None, gap: float = 0.0):
        nonlocal y
        font = "/F1" if bold else "/F2"
        color_cmd = f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg" if color else "0 0 0 rg"
        for line in _wrap(text, size):
            if y < 40:
                content.append("BT /F2 9 Tf 0.5 0.45 0.4 rg 1 0 0 1 54 40 Tm (continued...) Tj ET")
                return
            content.append(f"BT {font} {size} Tf {color_cmd} 1 0 0 1 54 {y:.0f} Tm ({_clean(line)}) Tj ET")
            y -= size * 1.35
        y -= gap

    emit(title, 20, True, accent)
    y -= 2
    emit(subtitle, 10, False, (0.42, 0.38, 0.32))
    y -= 18
    for heading, paragraphs in sections:
        emit(heading.upper(), 11, True, accent)
        y -= 3
        for paragraph in paragraphs:
            for line in _wrap(paragraph, 10):
                emit(line, 10, False)
        y -= 12

    stream = "\n".join(content).encode("latin-1")
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode()
    output += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(output)


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def build_project_sections(match, folder_name: str, letter_text: str | None = None) -> tuple[str, str, list[tuple[str, list[str]]]]:
    """Turn one scored role into the title/subtitle/sections of its PDF.

    Accepts either a FolderMatch object or the dict returned by the store.
    """
    project = _get(match, "project", {}) or {}
    title_field = _get(match, "title", "")
    company_field = _get(match, "company", "")
    area_field = _get(match, "area", "")
    score = _get(match, "score", None)
    score_label = f"{score}%" if score is not None else "no CV score"
    title = str(project.get("title") or f"{title_field} at {company_field}")
    subtitle = f"{title_field} at {company_field} · {score_label} · {project.get('domain') or area_field}"
    sections: list[tuple[str, list[str]]] = [
        ("About this project", [str(project.get("goal") or ""), str(project.get("why") or "")]),
        ("Targeted skills", [f"• {gap}" for gap in project.get("gap_skills", [])] or ["• A differentiating, tested piece of work in this area"]),
        ("What to build", [f"• {task}" for task in project.get("tasks", [])]),
        ("Deliverables", [f"• {item}" for item in project.get("deliverables", [])]),
        ("Acceptance criteria", [f"• {item}" for item in project.get("acceptance", [])]),
    ]
    if letter_text:
        excerpt = " ".join(str(letter_text).split())[:600]
        sections.append(("Your stated intent", [excerpt]))
    sections.append(("How to use this", [f"Folder: {folder_name}. This is a suggested project, not a claim of guaranteed interview success. "
                                        f"Complete the work, then update your CV with truthful evidence before re-scoring."]))
    return title, subtitle, sections


def render_project_pdf(match, folder_name: str, letter_text: str | None = None) -> bytes:
    title, subtitle, sections = build_project_sections(match, folder_name, letter_text)
    return render_document(title, subtitle, sections)
