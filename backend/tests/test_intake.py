"""Claim packages from several sources: CSV + FHIR JSON + PDF documents become one analysed batch (example data only)."""

import json
import random
import time

import httpx
import pytest

from app.intake import documents as docs
from app.intake.fhir import bundle_to_rows, rows_to_bundle
from app.intake.pdf_reader import PdfReadError, read_pdf
from app.services import document_qa, llm
from scripts.make_multisource_demo import _digital_pdf, _lines, _scanned_pdf
from tests.test_analysis_runs import call, setup, verifier_session
from tests.test_bpjs_csv_upload import _csv, _rows

NOTE = ("Perempuan 44 tahun datang dengan keluhan demam sejak 3 hari. TD 118/76 mmHg, nadi 88 x/menit, suhu 38.2 C. "
        "Kondisi ringan tanpa komplikasi. Dirawat 2 hari, pulang dengan kondisi membaik.")


def _pdf(doc, row, *, scanned=False):
    lines, narrative = _lines(doc, row, {})
    return _scanned_pdf(doc, row, lines, narrative, random.Random(3)) if scanned else _digital_pdf(doc, row, lines, narrative)


def _package(app, cookies, files, name="Paket uji"):
    csrf = {"X-CSRF-Token": cookies["cir_csrf"]}
    created = call(app, "POST", "/api/v1/intake/packages", cookies=cookies, json_body={"name": name}, headers=csrf)
    assert created.status_code == 201, created.text
    package_id = created.json()["package"]["package_id"]
    for file_name, raw in files:
        added = call(app, "PUT", f"/api/v1/intake/packages/{package_id}/files", cookies=cookies, content=raw,
                     headers={**csrf, "X-File-Name": file_name, "Content-Type": "application/octet-stream"})
        assert added.status_code == 200, added.text
    started = call(app, "POST", f"/api/v1/intake/packages/{package_id}/process", cookies=cookies, headers=csrf)
    assert started.status_code == 202, started.text
    deadline = time.time() + 180
    while time.time() < deadline:
        package = call(app, "GET", f"/api/v1/intake/packages/{package_id}", cookies=cookies).json()["package"]
        if package["status"] in ("ready", "failed"):
            return package
        time.sleep(0.3)
    raise AssertionError("package did not finish")


def test_a_package_of_csv_fhir_and_pdf_becomes_one_analysed_batch_with_cited_documents(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    rows = _rows(120)
    csv_rows, fhir_rows = rows[:100], rows[100:120]
    documented = dict(csv_rows[5], CATATAN_KLINIS=NOTE)
    wrong_total = dict(documented, FKL47=str(int(documented["FKL47"]) + 1_000_000))
    only_pdf = dict(rows[0], PSTV01="SYN7700001", FKL02="SYNV7700001", CATATAN_KLINIS=NOTE)
    files = [
        ("klaim.csv", _csv(csv_rows)),
        ("rme.json", json.dumps(rows_to_bundle([{k: v for k, v in row.items() if v} for row in fhir_rows])).encode()),
        ("resume.pdf", _pdf("resume_medis", documented)),
        ("tagihan.pdf", _pdf("rincian_tagihan", wrong_total)),
        ("a.pdf", _pdf("sep", only_pdf)), ("b.pdf", _pdf("resume_medis", only_pdf)), ("c.pdf", _pdf("rincian_tagihan", only_pdf)),
        ("bukan-pdf.pdf", b"%PDF-1.4 rusak"), ("catatan.txt", b"abaikan"),
    ]
    package = _package(app, verifier, files)
    assert package["status"] == "ready", package
    summary = package["summary"]
    assert summary["files"] == {"csv": 1, "fhir": 1, "pdf": 6, "ignored": 1}
    assert summary["claims"] == {"total": 121, "from_csv": 100, "from_fhir": 20, "from_pdf_only": 1, "duplicates_across_sources": 0}
    assert summary["documents"]["linked"] == 5 and summary["documents"]["unreadable"] == 1
    assert summary["enrichment"]["notes_from_documents"] == 2  # the documented CSV claim and the PDF-only claim
    # The document states another total than the claim data: recorded, and the data value is kept.
    assert summary["mismatch_count"] == 1
    mismatch = summary["mismatches"][0]
    assert mismatch["column"] == "FKL47" and mismatch["data_value"] == documented["FKL47"] and mismatch["document_value"] == wrong_total["FKL47"]

    run_id = package["run_id"]
    detail = call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier).json()["result"]
    assert detail["records_considered"] == 121
    case_id = mismatch["case_id"]
    listed = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{case_id}/documents", cookies=verifier)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [item["doc_type"] for item in body["items"]] == ["resume_medis", "rincian_tagihan"] and body["mismatch_count"] == 1
    assert body["evidence_found"] == ["clinical_note"] and body["question_engine"] == "text_search"
    note_fact = next(fact for fact in body["items"][0]["facts"] if fact["field"] == "catatan_klinis")
    assert note_fact["page"] == 1 and note_fact["verified"] and "pages" not in body["items"][0]
    # The note read from the PDF is the claim's note now (the CSV had none).
    note = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{case_id}/clinical-note", cookies=verifier).json()
    assert "tanpa komplikasi" in json.dumps(note, ensure_ascii=False)

    # The run lists every claim whose documents disagree with the data, also when no check flagged the claim.
    listed_mismatches = call(app, "GET", f"/api/v1/runs/{run_id}/document-mismatches", cookies=verifier).json()
    assert listed_mismatches["claim_count"] == 1 and listed_mismatches["mismatch_count"] == 1
    assert listed_mismatches["claims"][0]["case_id"] == case_id and listed_mismatches["claims"][0]["mismatches"][0]["column"] == "FKL47"
    assert call(app, "GET", f"/api/v1/runs/{run_id}/document-mismatches").status_code == 401

    document_id = body["items"][0]["document_id"]
    file = call(app, "GET", f"/api/v1/documents/{document_id}/file", cookies=verifier)
    assert file.status_code == 200 and file.content.startswith(b"%PDF") and file.headers["content-type"] == "application/pdf"
    assert call(app, "GET", f"/api/v1/documents/{document_id}/file").status_code == 401
    assert call(app, "GET", "/api/v1/documents/doc_unknown/file", cookies=verifier).status_code == 404

    csrf = {"X-CSRF-Token": verifier["cir_csrf"]}
    ask_url = f"/api/v1/runs/{run_id}/cases/{case_id}/documents/ask"
    answer = call(app, "POST", ask_url, cookies=verifier, json_body={"question": "Berapa hari pasien dirawat?"}, headers=csrf)
    assert answer.status_code == 200, answer.text
    assert answer.json()["engine"] == "text_search" and answer.json()["citations"][0]["page"] == 1
    assert call(app, "POST", ask_url, cookies=verifier, json_body={"question": "Berapa hari?"}).status_code == 403  # CSRF
    # A claim without documents has nothing to ask.
    other = next(key for key in detail["cases"] if key != case_id) if detail.get("cases") else None
    if other:
        empty = call(app, "POST", f"/api/v1/runs/{run_id}/cases/{other}/documents/ask", cookies=verifier,
                     json_body={"question": "Berapa hari?"}, headers=csrf)
        assert empty.status_code == 409
    # A processed package is closed.
    again = call(app, "PUT", f"/api/v1/intake/packages/{package['package_id']}/files", cookies=verifier, content=b"x",
                 headers={**csrf, "X-File-Name": "x.csv"})
    assert again.status_code == 409


def test_a_package_without_claim_data_or_with_real_participants_fails_without_storing_claims(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    assert _package(app, verifier, [("catatan.txt", b"tidak ada data")])["message_code"] == "NO_CLAIM_DATA"
    real = [dict(row, PSTV01=f"{index:010d}") for index, row in enumerate(_rows(40))]
    failed = _package(app, verifier, [("ekspor.csv", _csv(real))])
    assert failed["status"] == "failed" and failed["message_code"] == "CLAIM_DATA_REJECTED:real_participant_not_allowed"
    assert call(app, "GET", "/api/v1/intake/packages", cookies=verifier).json()["items"][0]["run_id"] is None
    assert call(app, "GET", "/api/v1/intake/packages").status_code == 401


def test_scanned_documents_are_read_by_ocr_with_the_same_facts(tmp_path):
    row = dict(_rows(3)[1], CATATAN_KLINIS=NOTE, FKL18="I500", FKL19="I-4-10-I")
    reading = read_pdf(_pdf("resume_medis", row, scanned=True))
    assert reading.scanned_pages == 1 and reading.pages[0].method == "ocr" and reading.pages[0].confidence > 0.9
    result = docs.read_document(reading, use_model=False)
    assert result.doc_type == "resume_medis"
    assert result.value("nomor_kunjungan") == row["FKL02"] and result.value("tanggal_masuk") == row["FKL03"]
    assert result.value("diagnosis_utama") == "I500"  # OCR reads the leading I as 1; ICD-10 starts with a letter
    assert docs.quote_on_page("Dirawat 2 hari, pulang dengan kondisi membaik", reading.pages[0].text)
    with pytest.raises(PdfReadError):
        read_pdf(b"bukan pdf")


def test_values_are_normalised_and_quotes_must_be_on_the_page():
    assert docs.normalise_value("tanggal_masuk", "04-09-2024") == "2024-09-04"
    assert docs.normalise_value("total_tagihan", "Rp 18.832.000") == "18832000"
    assert docs.normalise_value("diagnosis_utama", "1509") == "I509" and docs.normalise_value("diagnosis_utama", "J18.9") == "J189"
    assert docs.normalise_value("ina_cbg", "M-1-80-1") == "M-1-80-I" and docs.normalise_value("ina_cbg", "Q-5-44-0") == "Q-5-44-0"
    assert docs.normalise_value("diagnosis_sekunder", "A09.0, 1209") == "A090;I209"
    assert docs.quote_on_page("Tanggal Masuk: 04-09-2024", "No. Kartu: X\nTanggal  Masuk: 04-09-2024\n")
    assert not docs.quote_on_page("Dirawat 9 hari karena komplikasi berat", "Dirawat 2 hari, pulang membaik.")


def test_fhir_bundles_round_trip_to_the_same_claim_rows():
    rows = [{k: v for k, v in dict(row, FKL24="E119;I10", CATATAN_KLINIS=NOTE, JENIS_LAYANAN="special_drug", FKL44="DD-07-II",
                                   BUKTI_TERCATAT="prescription").items() if v} for row in _rows(6)]
    back, summary = bundle_to_rows(json.dumps(rows_to_bundle(rows)))
    assert back == rows and summary["claims"] == 7 and summary["skipped"] == 0
    from app.intake.fhir import FhirReadError
    with pytest.raises(FhirReadError):
        bundle_to_rows(b'{"resourceType": "Patient"}')


def test_model_answers_are_validated_and_citations_checked_against_the_page(monkeypatch):
    monkeypatch.setenv("CIR_LLM_BASE_URL", "http://model.internal/v1")
    monkeypatch.setenv("CIR_LLM_MODEL", "contoh-model")
    llm.reset_state()
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append(json)
        if json["messages"][0]["role"] == "system":  # this endpoint refuses the system role
            return httpx.Response(400, json={"error": {"message": "Developer instruction is not enabled"}})
        answer = {"ditemukan": True, "jawaban": "Pasien dirawat 2 hari.", "kutipan": [
            {"dokumen": 1, "halaman": 1, "kutipan": "Dirawat 2 hari, pulang dengan kondisi membaik"},
            {"dokumen": 1, "halaman": 1, "kutipan": "Dirawat 14 hari di ICU"}]}
        return httpx.Response(200, json={"model": "contoh-model", "choices": [{"message": {"content": "```json\n" + __import__("json").dumps(answer) + "\n```"}}]})

    monkeypatch.setattr(llm, "http_post", fake_post)
    documents = [{"document_id": "doc_1", "file_name": "resume.pdf", "doc_type_label": "Resume medis",
                  "pages": [{"number": 1, "text": NOTE}]}]
    result = document_qa.answer_question(documents, "Berapa hari pasien dirawat?")
    assert result["engine"] == "llm" and result["found"] and result["model"] == "contoh-model"
    assert [item["quote"] for item in result["citations"]] == ["Dirawat 2 hari, pulang dengan kondisi membaik"]
    assert result["unverified_citations"] == 1  # the invented quote is dropped
    assert len(calls) == 2 and calls[1]["messages"][0]["role"] == "user"
    llm.reset_state()


def test_a_page_the_ocr_is_unsure_about_is_read_again_by_the_vision_model(monkeypatch):
    from app.intake import pdf_reader

    row = dict(_rows(3)[1], CATATAN_KLINIS=NOTE)
    raw = _pdf("resume_medis", row, scanned=True)
    monkeypatch.setattr(pdf_reader, "ocr_image", lambda image: ("teks kabur", 0.41))
    assert read_pdf(raw).pages[0].method == "ocr"  # no model configured: the OCR text stays, flagged by its confidence
    monkeypatch.setenv("CIR_LLM_BASE_URL", "http://model.internal/v1")
    llm.reset_state()
    seen = {}

    def fake_post(url, *, headers, json, timeout):
        seen["parts"] = json["messages"][-1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"teks": "RESUME MEDIS\\nNo. Kunjungan: SYNV0000001"}'}}]})

    monkeypatch.setattr(llm, "http_post", fake_post)
    page = read_pdf(raw).pages[0]
    assert page.method == "ocr+ai" and "No. Kunjungan: SYNV0000001" in page.text and page.confidence == 0.41
    assert any(part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image/jpeg;base64,") for part in seen["parts"])
    llm.reset_state()


def test_zip_packages_are_expanded_and_unlinked_documents_are_reported_not_guessed(tmp_path):
    import io
    import zipfile

    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    rows = _rows(60)
    known = dict(rows[3], CATATAN_KLINIS=NOTE)
    stranger = dict(rows[4], FKL02="", CATATAN_KLINIS=NOTE)  # a resume medis that names no visit number
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("data/klaim.csv", _csv(rows))
        bundle.writestr("berkas/resume-ada.pdf", _pdf("resume_medis", known))
        bundle.writestr("berkas/resume-tanpa-nomor.pdf", _pdf("resume_medis", stranger))
        bundle.writestr("berkas/", b"")
    package = _package(app, verifier, [("paket.zip", archive.getvalue())])
    assert package["status"] == "ready", package
    summary = package["summary"]
    assert summary["files"] == {"csv": 1, "fhir": 0, "pdf": 2, "ignored": 0} and summary["claims"]["total"] == 61
    assert summary["documents"]["linked"] == 1 and summary["documents"]["unlinked"] == 1
    assert summary["problem_files"] == [{"file_name": "resume-tanpa-nomor.pdf", "status": "unlinked", "reason": "NO_VISIT_NUMBER"}]
    # The unlinked document fills nothing: only the linked claim got its note from a document.
    assert summary["enrichment"]["notes_from_documents"] == 1

    # The queue marks claims that have documents (and how many values disagree).
    run_id = package["run_id"]
    listed = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=50", cookies=verifier).json()["items"]
    assert all("documents" in item for item in listed)
    with_documents = [item for item in listed if item["documents"]]
    assert all(item["documents"] == {"documents": 1, "mismatches": 0} for item in with_documents)


def test_example_files_can_be_downloaded_without_answer_keys_and_uploaded_back(tmp_path):
    import io
    import zipfile

    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    listed = call(app, "GET", "/api/v1/intake/samples", cookies=verifier).json()["items"]
    assert [item["sample_id"] for item in listed] == ["paket-ringkas", "paket-lengkap", "klaim-csv"]
    small = call(app, "GET", "/api/v1/intake/samples/paket-ringkas", cookies=verifier)
    assert small.status_code == 200 and small.headers["content-type"] == "application/zip"
    assert "attachment" in small.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(small.content)).namelist()
    assert "klaim-eklaim.csv" in names and "rme-satusehat.json" in names
    assert sum(name.startswith("berkas/") for name in names) == 24
    assert not any("answers" in name for name in names)  # the answer key never leaves the server
    assert call(app, "GET", "/api/v1/intake/samples/kunci-jawaban", cookies=verifier).status_code == 404
    assert call(app, "GET", "/api/v1/intake/samples/paket-ringkas").status_code == 401
    package = _package(app, verifier, [("contoh-paket-klaim-ringkas.zip", small.content)])
    assert package["status"] == "ready", package
    summary = package["summary"]
    assert summary["claims"]["total"] == 29628 and summary["claims"]["from_pdf_only"] == 5
    assert summary["mismatch_count"] == 3 and summary["documents"]["linked"] == 24


def test_a_document_never_attaches_to_another_participant_or_another_analysis(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    rows = _rows(60)
    other_person = dict(rows[5], PSTV01="SYN9999999", CATATAN_KLINIS=NOTE)
    first = _package(app, verifier, [("klaim.csv", _csv(rows)), ("resume-lain.pdf", _pdf("resume_medis", other_person))], name="Paket A")
    summary = first["summary"]
    # Same visit number, other participant: the document is reported, not attached.
    assert summary["documents"]["linked"] == 0
    assert summary["problem_files"] == [{"file_name": "resume-lain.pdf", "status": "unlinked", "reason": "PARTICIPANT_MISMATCH"}]
    assert summary["enrichment"]["notes_from_documents"] == 0

    own = dict(rows[7], CATATAN_KLINIS=NOTE)
    second = _package(app, verifier, [("klaim.csv", _csv(rows)), ("resume.pdf", _pdf("resume_medis", own))], name="Paket B")
    from app.data_sources.bpjs_csv import UPLOAD_PSEUDONYM_SECRET
    from app.data_sources.bpjs_fkrtl_adapter import pseudonymous_case_id
    case_id = pseudonymous_case_id(own["PSTV01"], own["FKL02"], secret=UPLOAD_PSEUDONYM_SECRET)
    in_second = call(app, "GET", f"/api/v1/runs/{second['run_id']}/cases/{case_id}/documents", cookies=verifier).json()
    in_first = call(app, "GET", f"/api/v1/runs/{first['run_id']}/cases/{case_id}/documents", cookies=verifier)
    assert len(in_second["items"]) == 1
    # The first analysis did not receive that document: documents stay with the package of their analysis.
    assert in_first.status_code in (200, 404) and (in_first.status_code == 404 or in_first.json()["items"] == [])


def test_a_claim_is_built_from_documents_only_when_two_documents_agree_on_its_identity(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    rows = _rows(40)
    lone = dict(rows[0], PSTV01="SYN8800001", FKL02="SYNV8800001", CATATAN_KLINIS=NOTE)
    pair = dict(rows[1], PSTV01="SYN8800002", FKL02="SYNV8800002", CATATAN_KLINIS=NOTE)
    package = _package(app, verifier, [("klaim.csv", _csv(rows)), ("sendiri.pdf", _pdf("resume_medis", lone)),
                                       ("sep.pdf", _pdf("sep", pair)), ("resume.pdf", _pdf("resume_medis", pair))])
    summary = package["summary"]
    assert summary["claims"]["from_pdf_only"] == 1
    assert {"file_name": "sendiri.pdf", "status": "unlinked", "reason": "SINGLE_DOCUMENT_CLAIM"} in summary["problem_files"]


def test_the_overview_counts_ai_confirmed_claims_evidence_and_largest_bills_and_the_queue_sorts_by_amount(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    package = _package(app, verifier, [("klaim.csv", _csv(_rows(120)))])
    run_id = package["run_id"]
    summary = call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier).json()["result"]
    full = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]
    overview = summary["overview"]
    lanes = full["action_policy"]["cases"]
    threshold = overview["ai_threshold"]
    expected = sum(1 for case_id, lane in lanes.items() if lane["lane"] == "red"
                   and ((full["cases"][case_id].get("ml_anomaly") or {}).get("reference_percentile")
                        or (full["cases"][case_id].get("ml_anomaly") or {}).get("anomaly_percentile") or 0) >= threshold)
    assert overview["ai_confirmed_high"] == expected
    amounts = [item["amount"] for item in overview["top_high_claims"]]
    assert amounts == sorted(amounts, reverse=True)
    page = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=20&sort=billed", cookies=verifier).json()["items"]
    billed = [item["case"]["claim_billed_amount"] for item in page]
    assert all(value is not None for value in billed) and billed == sorted(billed, reverse=True)
    pipeline = call(app, "GET", f"/api/v1/runs/{run_id}/review-pipeline", cookies=verifier).json()
    assert [stage["stage"] for stage in pipeline["stages"]] == ["pending_review", "in_review", "awaiting_evidence", "escalated", "closed"]
    assert pipeline["needs_action"] == sum(1 for lane in lanes.values() if lane["lane"] in ("red", "yellow"))
    assert pipeline["stages"][0]["count"] == pipeline["needs_action"]


def test_wrong_files_are_listed_with_their_reason_and_never_stop_the_package(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    rows = _rows(50)
    no_visits = json.dumps({"resourceType": "Bundle", "type": "collection", "entry": []}).encode()
    package = _package(app, verifier, [
        ("klaim.csv", _csv(rows)),
        ("pasien.json", json.dumps({"resourceType": "Patient", "id": "x"}).encode()),  # FHIR, but not a Bundle
        ("kosong.json", no_visits),
        ("data.json", b'{"apa": 1}'),
        ("foto.pdf", b"\x89PNG\r\n\x1a\n...."),
        ("tabel.csv", b"a,b\n1,2\n"),
    ])
    assert package["status"] == "ready", package
    summary = package["summary"]
    assert summary["claims"]["total"] == len(rows)
    reasons = {item["file_name"]: item["reason"] for item in summary["ignored_files"]}
    assert reasons == {"pasien.json": "FHIR_NOT_A_BUNDLE", "kosong.json": "FHIR_NO_ENCOUNTERS", "data.json": "JSON_NOT_FHIR",
                       "foto.pdf": "NOT_A_PDF", "tabel.csv": "CSV_NOT_CLAIM_DATA"}
    assert summary["files"]["ignored"] == 5


def test_the_same_claim_in_csv_and_fhir_uses_the_medical_record_and_records_the_difference(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    rows = _rows(30)
    changed = dict(rows[3], FKL47=str(int(rows[3]["FKL47"]) + 500_000))
    bundle = json.dumps(rows_to_bundle([{k: v for k, v in changed.items() if v}])).encode()
    # The FHIR file first: the order of upload does not decide which source is used.
    package = _package(app, verifier, [("rme.json", bundle), ("klaim.csv", _csv(rows))])
    summary = package["summary"]
    assert summary["claims"]["total"] == len(rows) and summary["claims"]["from_fhir"] == 1
    assert summary["source_conflicts"]["count"] == 1
    conflict = summary["source_conflicts"]["items"][0]
    assert "FKL47" in conflict["columns"] and conflict["csv_file"] == "klaim.csv" and conflict["fhir_file"] == "rme.json"


def test_a_package_sent_twice_is_recognised_and_a_rejected_package_names_its_file(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    files = [("klaim.csv", _csv(_rows(30)))]
    first = _package(app, verifier, files, name="Pertama")
    second = _package(app, verifier, files, name="Kedua")
    assert first["summary"]["same_as"] is None
    assert second["summary"]["same_as"]["package_id"] == first["package_id"]
    real = [dict(row, PSTV01=f"{index:010d}") for index, row in enumerate(_rows(10))]
    failed = _package(app, verifier, [("benar.csv", _csv(_rows(10))), ("ekspor-asli.csv", _csv(real))])
    assert failed["status"] == "failed"
    assert failed["summary"]["failure"]["files"] == ["ekspor-asli.csv"]


def test_packages_can_be_cancelled_while_uploading_and_after_processing(tmp_path):
    from app.services import intake

    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    csrf = {"X-CSRF-Token": verifier["cir_csrf"]}
    db_path = app.state.run_db_path
    created = call(app, "POST", "/api/v1/intake/packages", cookies=verifier, json_body={"name": "Batal"}, headers=csrf).json()["package"]
    call(app, "PUT", f"/api/v1/intake/packages/{created['package_id']}/files", cookies=verifier, content=_csv(_rows(5)),
         headers={**csrf, "X-File-Name": "klaim.csv", "Content-Type": "application/octet-stream"})
    staging = intake._staging(db_path, created["package_id"])
    assert any(staging.iterdir())
    cancelled = call(app, "DELETE", f"/api/v1/intake/packages/{created['package_id']}", cookies=verifier, headers=csrf)
    assert cancelled.status_code == 200 and cancelled.json()["package"]["status"] == "cancelled"
    assert not staging.exists()
    assert call(app, "DELETE", f"/api/v1/intake/packages/{created['package_id']}", cookies=verifier).status_code == 403  # no CSRF

    rows = _rows(40)
    own = dict(rows[7], CATATAN_KLINIS=NOTE)
    done = _package(app, verifier, [("klaim.csv", _csv(rows)), ("resume.pdf", _pdf("resume_medis", own))], name="Salah kirim")
    from app.data_sources.bpjs_csv import UPLOAD_PSEUDONYM_SECRET
    from app.data_sources.bpjs_fkrtl_adapter import pseudonymous_case_id
    case_id = pseudonymous_case_id(own["PSTV01"], own["FKL02"], secret=UPLOAD_PSEUDONYM_SECRET)
    url = f"/api/v1/runs/{done['run_id']}/cases/{case_id}/documents"
    assert len(call(app, "GET", url, cookies=verifier).json()["items"]) == 1
    undone = call(app, "DELETE", f"/api/v1/intake/packages/{done['package_id']}", cookies=verifier, headers=csrf).json()["package"]
    assert undone["status"] == "cancelled"
    assert call(app, "GET", url, cookies=verifier).json()["items"] == []  # documents released from the claim
    archived = call(app, "GET", "/api/v1/runs?archived=true", cookies=verifier).json()["items"]
    assert done["run_id"] in {item["run_id"] for item in archived}


def test_abandoned_uploads_are_cleaned_up_and_only_claim_like_pages_go_to_the_model(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.intake.pdf_reader import PageText, PdfReading
    from app.services import intake

    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    csrf = {"X-CSRF-Token": verifier["cir_csrf"]}
    db_path = app.state.run_db_path
    old = call(app, "POST", "/api/v1/intake/packages", cookies=verifier, json_body={"name": "Lama"}, headers=csrf).json()["package"]
    with intake._connection(db_path) as connection:
        connection.execute("UPDATE intake_packages SET created_at=? WHERE package_id=?",
                           ((datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(), old["package_id"]))
    call(app, "POST", "/api/v1/intake/packages", cookies=verifier, json_body={"name": "Baru"}, headers=csrf)
    left = intake.get_package(db_path, old["package_id"])
    assert left["status"] == "cancelled" and left["message_code"] == "ABANDONED"
    assert not intake._staging(db_path, old["package_id"]).exists()

    def page(text):
        return PdfReading(pages=[PageText(number=1, text=text, method="text")])

    law = page("Undang-Undang Nomor 17 Tahun 2023 tentang Kesehatan. Pasal 1. Dalam undang-undang ini yang dimaksud dengan ...")
    claim = page("Nama pasien: X. No. SEP 0301R. Diagnosa utama J18.9. Rawat inap 3 hari. Dokter penanggung jawab: Y.")
    assert not docs.looks_like_claim(law) and docs.looks_like_claim(claim)
    calls = []
    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(docs, "read_with_model", lambda *args, **kwargs: calls.append(1) or ([], "lainnya", {}))
    docs.read_document(law)
    assert calls == []


def test_documents_are_kept_for_their_retention_and_never_while_they_are_evidence(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.data_sources.bpjs_csv import UPLOAD_PSEUDONYM_SECRET
    from app.data_sources.bpjs_fkrtl_adapter import pseudonymous_case_id
    from app.services import intake

    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)
    csrf = {"X-CSRF-Token": verifier["cir_csrf"]}
    db_path = app.state.run_db_path
    rows = _rows(40)
    kept, evidence = dict(rows[3], CATATAN_KLINIS=NOTE), dict(rows[5], CATATAN_KLINIS=NOTE)
    package = _package(app, verifier, [("klaim.csv", _csv(rows)), ("a.pdf", _pdf("resume_medis", kept)),
                                       ("b.pdf", _pdf("rincian_tagihan", evidence))])
    run_id = package["run_id"]
    evidence_case = pseudonymous_case_id(evidence["PSTV01"], evidence["FKL02"], secret=UPLOAD_PSEUDONYM_SECRET)
    kept_case = pseudonymous_case_id(kept["PSTV01"], kept["FKL02"], secret=UPLOAD_PSEUDONYM_SECRET)
    # One claim is escalated to audit: its document is evidence and stays.
    assert call(app, "PATCH", f"/api/v1/runs/{run_id}/cases/{evidence_case}/review", cookies=verifier,
                json_body={"review_status": "escalated", "note": None}, headers=csrf).status_code == 200
    policy = call(app, "GET", "/api/v1/intake/status", cookies=verifier).json()["retention"]
    assert policy["document_days"] == 3653 and policy["cancelled_days"] == 30

    assert intake.purge_expired_documents(db_path) == {"purged": 0, "held": 0}  # within retention
    later = datetime.now(timezone.utc) + timedelta(days=3654)
    assert intake.purge_expired_documents(db_path, now=later) == {"purged": 1, "held": 1}
    url = f"/api/v1/runs/{run_id}/cases/{{}}/documents"
    assert call(app, "GET", url.format(kept_case), cookies=verifier).json()["items"] == []
    assert len(call(app, "GET", url.format(evidence_case), cookies=verifier).json()["items"]) == 1
    with intake._connection(db_path) as connection:
        purged = connection.execute("SELECT file_name, sha256, pages_json, purged_at FROM claim_documents WHERE purged_at IS NOT NULL").fetchall()
    assert len(purged) == 1 and purged[0]["pages_json"] == "[]" and purged[0]["sha256"]  # the trail stays, the content goes
    assert not (intake.document_directory(db_path) / purged[0]["sha256"][:2] / f"{purged[0]['sha256']}.pdf").exists()

    # A cancelled package's documents go after 30 days.
    other = _package(app, verifier, [("klaim.csv", _csv(_rows(20))), ("c.pdf", _pdf("resume_medis", dict(_rows(20)[2], CATATAN_KLINIS=NOTE)))],
                     name="Salah kirim")
    call(app, "DELETE", f"/api/v1/intake/packages/{other['package_id']}", cookies=verifier, headers=csrf)
    monkeypatch.setenv("CIR_CANCELLED_DOCUMENT_DAYS", "30")
    assert intake.purge_expired_documents(db_path, now=datetime.now(timezone.utc) + timedelta(days=31))["purged"] == 1
