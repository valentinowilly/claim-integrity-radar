"""Text of every PDF page: the embedded text layer for digital PDFs, OCR for scanned pages.

A page with almost no embedded text is rendered to an image and read by the OCR engine. The demo and
laptop setup uses PP-OCRv6 through RapidOCR (ONNX runtime, CPU, offline); a production server would run the
document-parsing model named in the deployment guide on GPU behind the same ``ocr_image`` seam.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

MAX_PAGES = 40
MIN_TEXT_CHARS = 40  # fewer embedded characters than this: treat the page as a scan
RENDER_DPI = 200


class PdfReadError(ValueError):
    """The file is not a readable PDF (or exceeds the page limit); the message carries a code only."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class PageText:
    number: int  # 1-based
    text: str
    method: str  # "text" (embedded layer) or "ocr"
    confidence: float | None = None  # mean OCR score; None for embedded text


@dataclass
class PdfReading:
    pages: list[PageText] = field(default_factory=list)
    seconds: float = 0.0
    ocr_engine: str | None = None

    @property
    def scanned_pages(self) -> int:
        return sum(page.method != "text" for page in self.pages)

    def text(self) -> str:
        return "\n\n".join(f"[Halaman {page.number}]\n{page.text}" for page in self.pages)


_engine_lock = threading.Lock()
_ocr_lock = threading.Lock()
_engine: Any = None
OCR_ENGINE_NAME = "PP-OCRv6 (RapidOCR, CPU)"


def _ocr_engine() -> Any:
    global _engine
    with _engine_lock:
        if _engine is None:
            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            from rapidocr import RapidOCR

            _engine = RapidOCR()
        return _engine


def ocr_image(image: Any) -> tuple[str, float | None]:
    """Lines of a page image (PIL), top to bottom, and the mean recognition score.

    The recogniser sometimes misreads one long text line (low score, or gaps of several spaces). Such a line is
    cut out as one straight band and recognised again; the second reading replaces the first only when it is
    more confident and not much shorter.
    """
    import math

    image = image.convert("RGB")
    engine = _ocr_engine()
    with _ocr_lock:  # one page at a time: the engine is shared by the whole process
        # Flags are passed every time: a recognition-only call otherwise changes the engine's mode for later calls.
        result = engine(image, use_det=True, use_cls=True, use_rec=True)
    if result is None or result.boxes is None or not len(result.txts):
        return "", None
    # Scans are rarely straight: estimate the skew from the boxes' top edges and level the coordinates first.
    slopes = sorted(float(box[1][1] - box[0][1]) / float(box[1][0] - box[0][0]) for box in result.boxes if box[1][0] - box[0][0] > 40)
    skew = slopes[len(slopes) // 2] if slopes else 0.0
    if abs(skew) > math.tan(math.radians(12)):
        skew = 0.0
    items = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        ys = [float(point[1]) - float(point[0]) * skew for point in box]
        xs = [float(point[0]) for point in box]
        items.append({"y": sum(ys) / len(ys), "x": min(xs), "right": max(xs), "height": max(ys) - min(ys),
                      "text": text, "score": float(score)})
    items.sort(key=lambda item: (item["y"], item["x"]))
    lines: list[dict[str, Any]] = []
    for item in items:
        if lines and abs(item["y"] - lines[-1]["y"]) <= max(6.0, item["height"] * 0.45):
            line = lines[-1]
            line["parts"].append(item)
            line["y"] += (item["y"] - line["y"]) / len(line["parts"])
        else:
            lines.append({"y": item["y"], "parts": [item]})
    scores: list[float] = []
    texts: list[str] = []
    for line in lines:
        parts = sorted(line["parts"], key=lambda item: item["x"])
        text = "  ".join(part["text"] for part in parts)
        score = sum(part["score"] for part in parts) / len(parts)
        # A misread line shows as a low score, gaps of several spaces, or many tiny fragments.
        broken = (min(part["score"] for part in parts) < 0.9 or any("   " in part["text"] for part in parts)
                  or (len(parts) >= 3 and sum(len(part["text"]) for part in parts) / len(parts) < 5))
        if broken:
            again = _recognise_band(engine, image, line["y"], max(part["height"] for part in parts), parts[0]["x"],
                                    max(part["right"] for part in parts), skew)
            if again and again[1] > score and len(again[0]) >= 0.8 * len(text.replace(" ", "")):
                text, score = again
        texts.append(text)
        scores.append(score)
    return "\n".join(texts), round(sum(scores) / len(scores), 4)


def _recognise_band(engine: Any, image: Any, y: float, height: float, left: float, right: float, skew: float) -> tuple[str, float] | None:
    """Recognise one text line cut out along the page skew (recognition only, no detection)."""
    from PIL import Image

    half = max(10.0, height * 0.6)
    x0, x1 = max(0.0, left - 8), min(float(image.width - 1), right + 8)
    if x1 - x0 < 40:
        return None
    # Corners of the slanted band: upper left, lower left, lower right, upper right (the order Image.QUAD expects).
    quad = (x0, y + x0 * skew - half, x0, y + x0 * skew + half, x1, y + x1 * skew + half, x1, y + x1 * skew - half)
    crop = image.transform((int(x1 - x0), int(2 * half)), Image.QUAD, quad, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    try:
        with _ocr_lock:
            result = engine(crop, use_det=False, use_cls=False, use_rec=True)
    except Exception:  # the recogniser refused the crop: keep the first reading
        return None
    if result is None or not getattr(result, "txts", None):
        return None
    return str(result.txts[0]).strip(), float(result.scores[0])


LOW_CONFIDENCE = 0.85


def transcribe_with_model(image: Any) -> str | None:
    """The page text as read by the configured vision-language model; None when no model is available or it fails."""
    import base64

    from pydantic import BaseModel, Field

    from app.services import llm

    if not llm.configured():
        return None

    class Transcript(BaseModel):
        teks: str = Field(description="Seluruh teks halaman, baris demi baris, apa adanya.")

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85)
    url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    try:
        answer, _usage = llm.chat_json(
            "Anda menyalin teks dari gambar halaman dokumen klaim rumah sakit. Salin apa adanya, baris demi baris, "
            "tanpa menambah, meringkas, atau memperbaiki isi. Bagian yang tidak terbaca ditulis [tidak terbaca].",
            "Salin seluruh teks pada halaman ini.", Transcript, max_tokens=3000, images=[url])
    except llm.LlmError:
        return None
    return answer.teks.strip() or None


def read_pdf(raw: bytes, *, max_pages: int = MAX_PAGES, force_ocr: bool = False) -> PdfReading:
    if not raw.startswith(b"%PDF"):
        raise PdfReadError("NOT_A_PDF")
    started = time.monotonic()
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise PdfReadError("PDF_ENCRYPTED")
        count = len(reader.pages)
    except PdfReadError:
        raise
    except Exception as exc:  # malformed file
        raise PdfReadError("PDF_UNREADABLE") from exc
    if count == 0:
        raise PdfReadError("PDF_EMPTY")
    if count > max_pages:
        raise PdfReadError("PDF_TOO_MANY_PAGES")
    reading = PdfReading()
    document = None
    for index in range(count):
        try:
            embedded = (reader.pages[index].extract_text() or "").strip()
        except Exception:
            embedded = ""
        if not force_ocr and len(embedded) >= MIN_TEXT_CHARS:
            reading.pages.append(PageText(index + 1, embedded, "text"))
            continue
        if document is None:
            import pypdfium2

            document = pypdfium2.PdfDocument(raw)
        image = document[index].render(scale=RENDER_DPI / 72).to_pil()
        text, confidence = ocr_image(image)
        method = "ocr"
        if confidence is None or confidence < LOW_CONFIDENCE:
            # Second reader for pages the OCR engine is unsure about (faint scans, handwriting): the vision model.
            better = transcribe_with_model(image)
            if better:
                text, method = better, "ocr+ai"
        reading.pages.append(PageText(index + 1, text, method, confidence))
        reading.ocr_engine = OCR_ENGINE_NAME
    if document is not None:
        document.close()
    reading.seconds = round(time.monotonic() - started, 2)
    return reading


def render_page_png(raw: bytes, page: int, *, dpi: int = 110) -> bytes:
    """One page as a PNG (for models that read images, and for previews)."""
    import pypdfium2

    document = pypdfium2.PdfDocument(raw)
    try:
        if not 1 <= page <= len(document):
            raise PdfReadError("PAGE_OUT_OF_RANGE")
        image = document[page - 1].render(scale=dpi / 72).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    finally:
        document.close()
