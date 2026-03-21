import asyncio
import logging
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


class PDFDownloader:
    def __init__(self, pdf_dir: Path):
        self.pdf_dir = pdf_dir
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

    def _pdf_path(self, arxiv_id: str) -> Path:
        safe_id = arxiv_id.replace("/", "_").replace(".", "_")
        return self.pdf_dir / f"{safe_id}.pdf"

    async def download(self, arxiv_id: str, pdf_url: str) -> Path:
        """Download PDF from arxiv. Returns path to saved file."""
        path = self._pdf_path(arxiv_id)
        if path.exists():
            logger.debug(f"PDF already cached: {arxiv_id}")
            return path

        import urllib.request

        def _download():
            urllib.request.urlretrieve(pdf_url, path)

        await asyncio.to_thread(_download)
        logger.info(f"Downloaded PDF: {arxiv_id} -> {path}")
        return path

    async def extract_text(self, arxiv_id: str, pdf_url: str) -> str:
        """Download PDF and extract full text."""
        path = await self.download(arxiv_id, pdf_url)
        return await asyncio.to_thread(self._extract_text_sync, path)

    @staticmethod
    def _extract_text_sync(path: Path) -> str:
        """Extract text from PDF using PyMuPDF."""
        doc = fitz.open(path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
