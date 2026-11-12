"""Questions about one claim's documents ("Tanya berkas"): answers that cite the page they come from.

The model sees only the page texts of that claim's documents. Every citation is checked against the cited page;
citations that cannot be found there are dropped, and an answer left without any is reported as unproven.
Without a model the same question becomes a text search over the pages.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.intake import documents as docs
from app.services import llm

MAX_CONTEXT_CHARS = 60_000
SYSTEM_PROMPT = """Anda membantu verifikator klaim JKN membaca berkas satu klaim.
Jawab pertanyaan HANYA dari isi berkas yang diberikan, dalam bahasa Indonesia yang singkat dan jelas.
- Setiap pernyataan harus didukung kutipan: nomor dokumen, nomor halaman, dan kutipan pendek yang PERSIS ada di halaman itu.
- Bila jawabannya tidak ada di berkas, isi ditemukan=false dan katakan bahwa berkas tidak memuatnya. Jangan menebak.
- Jangan memberi keputusan apakah klaim curang; itu wewenang verifikator."""
STOP_WORDS = {"apa", "apakah", "yang", "dan", "atau", "dari", "pada", "untuk", "berapa", "kapan", "siapa", "ada", "ini", "itu",
              "dengan", "saja", "bagaimana", "klaim", "pasien"}


class Citation(BaseModel):
    dokumen: int = Field(ge=1, description="Nomor dokumen seperti pada daftar.")
    halaman: int = Field(ge=1)
    kutipan: str


class Answer(BaseModel):
    ditemukan: bool
    jawaban: str = Field(description="Paling banyak empat kalimat.")
    kutipan: list[Citation] = Field(max_length=6)


def _cite(documents: list[dict[str, Any]], index: int, page: int, quote: str) -> dict[str, Any] | None:
    if not 1 <= index <= len(documents):
        return None
    document = documents[index - 1]
    text = next((item["text"] for item in document.get("pages", []) if item["number"] == page), None)
    if text is None or not docs.quote_on_page(quote, text):
        return None
    return {"document_id": document["document_id"], "file_name": document["file_name"],
            "doc_type_label": document["doc_type_label"], "page": page, "quote": quote[:300]}


def answer_question(documents: list[dict[str, Any]], question: str) -> dict[str, Any]:
    """``documents`` carry their page texts (``documents_for_case(..., pages=True)``)."""
    reason = "LLM_NOT_CONFIGURED"
    if llm.configured():
        parts: list[str] = []
        used = 0
        for index, document in enumerate(documents, start=1):
            for page in document.get("pages", []):
                block = (f'<dokumen nomor="{index}" jenis="{document["doc_type_label"]}" halaman="{page["number"]}">\n'
                         f'{page["text"]}\n</dokumen>')
                if used + len(block) > MAX_CONTEXT_CHARS:
                    break
                parts.append(block)
                used += len(block)
        try:
            answer, usage = llm.chat_json(SYSTEM_PROMPT, "\n\n".join(parts) + f"\n\nPertanyaan verifikator: {question}",
                                          Answer, max_tokens=3000)
            citations = [item for item in (_cite(documents, c.dokumen, c.halaman, c.kutipan) for c in answer.kutipan) if item]
            unproven = answer.ditemukan and not citations
            return {"engine": "llm", "model": usage.get("model"), "found": answer.ditemukan and bool(citations),
                    "answer": answer.jawaban.strip(), "citations": citations,
                    "unverified_citations": len(answer.kutipan) - len(citations),
                    "note": ("Jawaban ini tidak memiliki kutipan yang dapat dicocokkan dengan berkas; perlakukan sebagai belum terbukti."
                             if unproven else None), "fallback_reason": None}
        except llm.LlmError as exc:
            reason = exc.code
    words = {word for word in re.findall(r"[a-z0-9]{3,}", question.lower()) if word not in STOP_WORDS}
    hits = []
    for index, document in enumerate(documents, start=1):
        for page in document.get("pages", []):
            for line in page["text"].splitlines():
                score = sum(word in line.lower() for word in words)
                if score:
                    hits.append((score, index, page["number"], line.strip()))
    hits.sort(key=lambda item: -item[0])
    citations = [item for item in (_cite(documents, index, page, line) for _score, index, page, line in hits[:5]) if item]
    return {"engine": "text_search", "model": None, "found": bool(citations),
            "answer": ("Model bahasa tidak tersedia. Berikut baris berkas yang paling cocok dengan kata dalam pertanyaan."
                       if citations else "Model bahasa tidak tersedia dan tidak ada baris berkas yang cocok dengan pertanyaan."),
            "citations": citations, "unverified_citations": 0, "note": None, "fallback_reason": reason}
