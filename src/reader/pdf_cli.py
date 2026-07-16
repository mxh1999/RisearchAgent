from __future__ import annotations

from pathlib import Path

from src.reader.page_extractor import extract_pages_from_pdf
from src.reader.staged_models import PageText


def render_extracted_pages(pages: list[PageText]) -> str:
    chunks = [f"[Page {page.page}]\n{page.text}" for page in pages]
    return "\n\n".join(chunks).rstrip() + "\n"


def write_pdf_extraction(args) -> Path | None:
    pages = extract_pages_from_pdf(Path(args.pdf), max_pages=args.max_pages)
    rendered = render_extracted_pages(pages)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        return output_path
    print(rendered, end="")
    return None


def run_pdf_command(args) -> None:
    if args.pdf_command == "extract":
        output_path = write_pdf_extraction(args)
        if output_path is not None:
            print(f"PDF extraction: {output_path}")
        return
    raise ValueError(f"Unknown pdf command: {args.pdf_command}")
