from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "output" / "pdf" / "bob_ide_assignment_checklist_audit_updated.pdf"
EVALUATION = ROOT / "output" / "pdf" / "Bob_Model_Performance_Evaluation_2026-08-06.pdf"
OUTPUT = ROOT / "output" / "pdf" / "Bob_IDE_Assignment_Checklist_with_Model_Evaluation_2026-08-06.pdf"


def append_document(writer: PdfWriter, source: Path) -> tuple[int, int]:
    reader = PdfReader(str(source))
    start = len(writer.pages)
    for page in reader.pages:
        writer.add_page(page)
    return start, len(reader.pages)


def main() -> None:
    writer = PdfWriter()
    checklist_start, checklist_pages = append_document(writer, CHECKLIST)
    evaluation_start, evaluation_pages = append_document(writer, EVALUATION)

    writer.add_outline_item("Checklist audit", checklist_start)
    writer.add_outline_item("Model performance evaluation", evaluation_start)
    writer.add_metadata({
        "/Title": "Bob IDE Assignment Checklist and Model Performance Evaluation",
        "/Author": "Bob IDE project evaluation",
        "/Subject": "Module 10 checklist audit with reviewer metrics and evidence",
    })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("wb") as stream:
        writer.write(stream)
    print(f"{OUTPUT} ({checklist_pages} checklist pages + {evaluation_pages} evaluation pages)")


if __name__ == "__main__":
    main()
