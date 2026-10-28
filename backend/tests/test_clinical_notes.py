"""Clinical notes of uploaded files: the cloned-note check and the stage 2 AI reading aid (fake client)."""

from types import SimpleNamespace

import httpx
import pytest

from app.analytics.ml_model import MODEL_DIR_VARIABLE
from app.analytics.note_similarity import MIN_WORDS, detect_cloned_notes, note_fingerprint
from app.data_sources.bpjs_csv import UPLOAD_PSEUDONYM_SECRET, parse_bpjs_csv
from app.data_sources.bpjs_fkrtl_adapter import pseudonymous_case_id
from app.services import clinical_ai
from tests.test_analysis_runs import call, create_run, import_batch, operator_session, setup, verifier_session
from tests.test_bpjs_csv_upload import COLUMNS, _csv, _rows, _upload, artifact_dir  # noqa: F401 (fixture)

NOTE_COLUMNS = COLUMNS + ("CATATAN_KLINIS",)
TEMPLATE = ("Laki-laki 54 tahun datang dengan keluhan nyeri dada sejak 2 hari. TD 150/90 mmHg, nadi 88 x/menit, "
            "suhu 36.8 C. Kondisi ringan tanpa komplikasi. Dirawat 3 hari, pulang dengan kondisi membaik.")


def _note(index):
    return (f"Perempuan {20 + index % 60} tahun datang dengan keluhan demam sejak {1 + index % 9} hari. "
            f"TD {100 + index % 60}/{60 + index % 30} mmHg, nadi {60 + index % 50} x/menit, catatan nomor {index}.")


def _noted_rows():
    rows = _rows()
    for index, row in enumerate(rows):
        row["CATATAN_KLINIS"] = _note(index)
    # Three claims of three different participants with one note copied word for word.
    for row in rows[10:13]:
        row["CATATAN_KLINIS"] = TEMPLATE
    rows[20]["CATATAN_KLINIS"] = ""  # no note: the check does not apply
    rows[21]["CATATAN_KLINIS"] = "Kontrol rutin, tidak ada keluhan."  # too short to assess
    return rows


def _case(row):
    return pseudonymous_case_id(row["PSTV01"], row["FKL02"], secret=UPLOAD_PSEUDONYM_SECRET)


# ---- the detector
def test_fingerprint_ignores_case_and_punctuation_but_not_numbers():
    assert note_fingerprint(TEMPLATE) == note_fingerprint(TEMPLATE.upper().replace(",", " ").replace(".", " ; "))
    assert note_fingerprint(TEMPLATE) != note_fingerprint(TEMPLATE.replace("150/90", "150/91"))
    assert note_fingerprint(" ".join(["kata"] * (MIN_WORDS - 1))) is None


def test_cloned_notes_need_two_participants_and_never_copy_the_text():
    def record(case, participant, note):
        return {"case_id": case, "participant_token": participant, "clinical_note": note}
    result = detect_cloned_notes([
        record("syn-c1", "p1", TEMPLATE), record("syn-c2", "p2", TEMPLATE + "  "), record("syn-c3", "p3", TEMPLATE.lower()),
        record("syn-c4", "p4", TEMPLATE.replace("54 tahun", "55 tahun")),
        # The same participant twice is a repeat-billing matter, not a cloned record.
        record("syn-c5", "p5", _note(1)), record("syn-c6", "p5", _note(1)),
        record("syn-c7", "p6", None), record("syn-c8", "p7", "pendek saja"),
    ])
    assert [group["case_ids"] for group in result["candidate_groups"]] == [["syn-c1", "syn-c2", "syn-c3"]]
    assert result["candidate_groups"][0]["distinct_participant_count"] == 3
    assert result["candidate_count"] == 3 and result["assessed_count"] == 6 and result["status"] == "complete"
    assert result["unassessed_case_ids"] == ["syn-c8"] and result["not_applicable_cases"] == [{"case_id": "syn-c7"}]
    assert "nyeri dada" not in str(result)


def test_without_any_note_the_check_is_not_applicable():
    result = detect_cloned_notes([{"case_id": "syn-c1", "participant_token": "p1"}])
    assert result["status"] == "not_applicable" and result["candidate_groups"] == []


def test_the_parser_keeps_notes_optional_and_bounded():
    rows = _noted_rows()
    records, summary = parse_bpjs_csv(_csv(rows, NOTE_COLUMNS))
    assert summary["error_count"] == 0
    notes = {record["case_id"]: record["clinical_note"] for record in records}
    assert notes[_case(rows[10])] == TEMPLATE and notes[_case(rows[20])] is None
    without, _ = parse_bpjs_csv(_csv(rows))
    assert all(record["clinical_note"] is None for record in without)
    rows[0]["CATATAN_KLINIS"] = "x" * 9000
    assert len(parse_bpjs_csv(_csv(rows, NOTE_COLUMNS))[0][0]["clinical_note"]) == 4000


# ---- an uploaded file end to end
class FakeClient:
    """Stands in for anthropic.Anthropic(); records the calls it gets."""

    def __init__(self, parsed=None, stop_reason="end_turn"):
        self.calls = []
        self.parsed, self.stop_reason = parsed, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.parsed, stop_reason=self.stop_reason, model=kwargs["model"])


class FakeOllama:
    """Stands in for the local Ollama server (httpx.get / httpx.post); records the chat requests."""

    def __init__(self, content=None, models=("qwen3:4b",), error=None, status=200):
        self.calls, self.content, self.models, self.error, self.status = [], content, models, error, status

    def get(self, url, timeout=None):
        if self.error:
            raise self.error
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"models": [{"name": m} for m in self.models]})

    def post(self, url, json=None, timeout=None):
        self.calls.append(json)
        if self.error:
            raise self.error
        return SimpleNamespace(status_code=self.status, json=lambda: {"message": {"content": self.content}})


FACTS = clinical_ai.NoteFacts(keparahan_menurut_catatan="tidak_disebut", komplikasi_atau_komorbid="tidak_disebut",
                              lama_rawat_menurut_catatan_hari=None, menyebut_lanjutan_perawatan_sebelumnya=False)
# What the (fake) model returns: facts from the note first, then its verdict.
VERDICT = clinical_ai.ModelReading(
    fakta_catatan=FACTS, verdict="mencurigakan", ringkasan="Catatan menyebut kondisi ringan, kode menagih keparahan berat.",
    alasan=["Tidak ada komplikasi yang tercatat."], yang_perlu_diperiksa=["Resume medis lengkap."])


def test_reconcile_raises_the_verdict_on_plain_contradictions_only():
    claim = {"claim_group": "K-1-17-III", "stay_days": 9}
    calm = VERDICT.model_copy(update={"verdict": "sesuai"})
    assert clinical_ai.reconcile(claim, calm).verdict == "sesuai"
    mild = calm.model_copy(update={"fakta_catatan": FACTS.model_copy(update={"komplikasi_atau_komorbid": "tidak"})})
    raised = clinical_ai.reconcile(claim, mild)
    assert raised.verdict == "mencurigakan" and "keparahan III" in raised.alasan[0]
    assert raised.ringkasan.startswith("Fakta yang dibaca dari catatan bertentangan")
    stay = calm.model_copy(update={"fakta_catatan": FACTS.model_copy(update={"lama_rawat_menurut_catatan_hari": 4})})
    assert "4 hari" in clinical_ai.reconcile(claim, stay).alasan[0]
    resumed = calm.model_copy(update={"fakta_catatan": FACTS.model_copy(update={"menyebut_lanjutan_perawatan_sebelumnya": True})})
    assert clinical_ai.reconcile(claim, resumed).verdict == "perlu_dicek"
    # A mild note under severity I is not a contradiction.
    assert clinical_ai.reconcile({**claim, "claim_group": "K-1-17-I"}, mild).verdict == "sesuai"
    # One day apart is a counting convention (admission day or nights), not a contradiction.
    near = calm.model_copy(update={"fakta_catatan": FACTS.model_copy(update={"lama_rawat_menurut_catatan_hari": 8})})
    assert clinical_ai.reconcile(claim, near).verdict == "sesuai"


def test_the_wording_checks_catch_what_the_model_missed():
    claim = {"claim_group": "A-4-10-I", "stay_days": 9, "clinical_note": "Observasi 2x24 jam, kondisi stabil, pulang."}
    calm = VERDICT.model_copy(update={"verdict": "sesuai"})  # the model read no stay at all
    raised = clinical_ai.reconcile(claim, calm)
    assert raised.verdict == "perlu_dicek" and "2 hari" in raised.alasan[0]
    # When the model already read the stay, the same contradiction is not listed twice.
    read = calm.model_copy(update={"fakta_catatan": FACTS.model_copy(update={"lama_rawat_menurut_catatan_hari": 2})})
    assert sum("hari" in text for text in clinical_ai.reconcile(claim, read).alasan) == 1


def test_a_mild_reading_needs_the_note_to_be_silent_on_comorbidities():
    claim = {"claim_group": "J-4-16-II", "stay_days": 5}
    calm = VERDICT.model_copy(update={"verdict": "sesuai"})
    silent = calm.model_copy(update={"fakta_catatan": FACTS.model_copy(update={"keparahan_menurut_catatan": "ringan"})})
    assert clinical_ai.reconcile(claim, silent).verdict == "perlu_dicek"
    comorbid = calm.model_copy(update={"fakta_catatan": FACTS.model_copy(
        update={"keparahan_menurut_catatan": "ringan", "komplikasi_atau_komorbid": "ya"})})
    assert clinical_ai.reconcile(claim, comorbid).verdict == "sesuai"


@pytest.mark.parametrize(("note", "stay"), [
    ("Observasi 2x24 jam, kondisi stabil, diizinkan pulang.", 2),
    ("Pasien dirawat selama empat hari lalu pulang.", 4),
    ("Respons baik dengan antibiotik, pulang pada hari perawatan kedua.", 2),
    ("Antibiotik, pulang setelah 3 hari dirawat.", 3),
    ("Rawat inap 3 hari dengan antibiotik iv.", 3),
    ("Demam 4 hari disertai mual.", None),  # how long the complaint lasted, not the stay
])
def test_the_fallback_reads_the_stay_in_common_phrasings(note, stay):
    assert clinical_ai.stay_in_note(note.lower()) == stay


def _use_ollama(monkeypatch, fake):
    monkeypatch.setattr(clinical_ai, "http_get", fake.get)
    monkeypatch.setattr(clinical_ai, "http_post", fake.post)
    clinical_ai.reset_availability_cache()


def _timeout(*_args, **_kwargs):
    raise httpx.ReadTimeout("slow")


@pytest.fixture()
def noted_run(tmp_path, monkeypatch, artifact_dir):  # noqa: F811
    monkeypatch.setenv(MODEL_DIR_VARIABLE, str(artifact_dir))
    from app.analytics.ml_model import _category_labels_from
    _category_labels_from.cache_clear()
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", clinical_ai.SWITCH_VARIABLE, clinical_ai.PROVIDER_VARIABLE,
                 clinical_ai.MODEL_VARIABLE, clinical_ai.OLLAMA_URL_VARIABLE):
        monkeypatch.delenv(name, raising=False)
    # No Ollama server in tests unless a test provides a fake one.
    _use_ollama(monkeypatch, FakeOllama(error=httpx.ConnectError("no server")))
    app, batch_db, users = setup(tmp_path)
    operator, verifier = operator_session(app, users), verifier_session(app, users)
    rows = _noted_rows()
    uploaded = _upload(app, operator, _csv(rows, NOTE_COLUMNS))
    assert uploaded.status_code == 201 and uploaded.json()["batch"]["status"] == "ready", uploaded.text
    created = create_run(app, operator, uploaded.json()["batch"]["batch_id"])
    assert created.status_code == 201, created.text
    yield SimpleNamespace(app=app, batch_db=batch_db, users=users, operator=operator, verifier=verifier, rows=rows,
                          run_id=created.json()["run"]["run_id"])
    clinical_ai.reset_availability_cache()


def _note_url(ctx, row, tail="clinical-note"):
    return f"/api/v1/runs/{ctx.run_id}/cases/{_case(row)}/{tail}"


def _analyse(ctx, row):
    return call(ctx.app, "POST", _note_url(ctx, row, "clinical-analysis"), cookies=ctx.verifier,
                headers={"X-CSRF-Token": ctx.verifier["cir_csrf"]})


def test_an_uploaded_file_with_notes_flags_the_clone_and_keeps_note_text_out_of_the_result(noted_run):
    ctx = noted_run
    body = call(ctx.app, "GET", f"/api/v1/runs/{ctx.run_id}", cookies=ctx.verifier).text
    summary = call(ctx.app, "GET", f"/api/v1/runs/{ctx.run_id}?view=summary", cookies=ctx.verifier).json()
    indicator = next(item for item in summary["result"]["indicators"] if item["code"] == "cloned_clinical_note_candidate")
    # "partial": the one short note is counted as not assessed, like any check with unassessed claims.
    assert indicator["status"] == "partial" and indicator["candidate_count"] == 3 and indicator["unassessed_count"] == 1
    assert "nyeri dada" not in body and "catatan nomor" not in body and "nyeri dada" not in str(summary)


def test_without_a_language_model_the_fallback_reading_answers_and_is_labelled(noted_run):
    ctx = noted_run
    shown = call(ctx.app, "GET", _note_url(ctx, ctx.rows[10]), cookies=ctx.verifier)
    assert shown.status_code == 200, shown.text
    payload = shown.json()
    assert payload["clinical_note"] == TEMPLATE and payload["source"] == "uploaded_example"
    assert payload["ai_configured"] is False and payload["ai_provider"] == "ollama" and payload["analysis"] is None
    # Like any degraded dependency: the request still succeeds, with the fallback reading and its reason.
    response = _analyse(ctx, ctx.rows[10])
    assert response.status_code == 200, response.text
    analysis = response.json()["analysis"]
    assert analysis["engine"] == "fallback" and analysis["model"] == clinical_ai.FALLBACK_MODEL
    assert analysis["fallback_reason"] == "CLINICAL_AI_NOT_CONFIGURED"
    assert call(ctx.app, "GET", _note_url(ctx, ctx.rows[10]), cookies=ctx.verifier).json()["analysis"]["engine"] == "fallback"
    assert call(ctx.app, "GET", _note_url(ctx, ctx.rows[20]), cookies=ctx.verifier).json()["clinical_note"] is None


def test_the_local_model_reading_is_stored_and_shown_and_never_changes_the_queue(noted_run, monkeypatch):
    ctx = noted_run
    fake = FakeOllama(content=VERDICT.model_dump_json())
    _use_ollama(monkeypatch, fake)
    before = call(ctx.app, "GET", f"/api/v1/runs/{ctx.run_id}?view=summary", cookies=ctx.verifier).json()["result"]
    assert call(ctx.app, "GET", _note_url(ctx, ctx.rows[10]), cookies=ctx.verifier).json()["ai_configured"] is True
    response = _analyse(ctx, ctx.rows[10])
    assert response.status_code == 200, response.text
    analysis = response.json()["analysis"]
    assert analysis["verdict"] == "mencurigakan" and analysis["engine"] == "llm" and analysis["model"] == "qwen3:4b"
    sent = fake.calls[0]
    assert sent["model"] == "qwen3:4b" and sent["stream"] is False
    assert sent["format"] == clinical_ai.ModelReading.model_json_schema()
    prompt = sent["messages"][1]["content"]
    assert f"<catatan_klinis>\n{TEMPLATE}\n</catatan_klinis>" in prompt
    # Only claim facts reach the model: no participant or visit numbers, no case reference.
    assert ctx.rows[10]["PSTV01"] not in prompt and ctx.rows[10]["FKL02"] not in prompt and _case(ctx.rows[10]) not in prompt
    shown = call(ctx.app, "GET", _note_url(ctx, ctx.rows[10]), cookies=ctx.verifier).json()
    assert shown["analysis"]["verdict"] == "mencurigakan"
    assert shown["analysis"]["requested_by"] == ctx.users["verifier"]["username"]
    after = call(ctx.app, "GET", f"/api/v1/runs/{ctx.run_id}?view=summary", cookies=ctx.verifier).json()["result"]
    assert after == before


@pytest.mark.parametrize("fake, reason", [
    (FakeOllama(content="bukan json"), "CLINICAL_AI_INVALID_ANSWER"),
    (FakeOllama(content='{"verdict": "fraud"}'), "CLINICAL_AI_INVALID_ANSWER"),
    (FakeOllama(content=None, status=500), "CLINICAL_AI_UNAVAILABLE"),
])
def test_a_failed_local_model_answer_falls_back_without_an_error(noted_run, monkeypatch, fake, reason):
    ctx = noted_run
    _use_ollama(monkeypatch, fake)
    response = _analyse(ctx, ctx.rows[10])
    assert response.status_code == 200, response.text
    analysis = response.json()["analysis"]
    assert analysis["engine"] == "fallback" and analysis["fallback_reason"] == reason


def test_a_timeout_falls_back(noted_run, monkeypatch):
    ctx = noted_run
    _use_ollama(monkeypatch, FakeOllama(content=VERDICT.model_dump_json()))
    monkeypatch.setattr(clinical_ai, "http_post", _timeout)
    analysis = _analyse(ctx, ctx.rows[10]).json()["analysis"]
    assert analysis["engine"] == "fallback" and analysis["fallback_reason"] == "CLINICAL_AI_TIMEOUT"


def test_the_anthropic_provider_is_used_only_when_chosen(noted_run, monkeypatch):
    ctx = noted_run
    monkeypatch.setenv(clinical_ai.PROVIDER_VARIABLE, "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    fake = FakeClient(parsed=VERDICT)
    monkeypatch.setattr(clinical_ai, "client_factory", lambda: fake)
    analysis = _analyse(ctx, ctx.rows[10]).json()["analysis"]
    assert analysis["engine"] == "llm" and fake.calls[0]["model"] == "claude-opus-5-5"
    assert fake.calls[0]["output_format"] is clinical_ai.ModelReading
    declined = FakeClient(parsed=None, stop_reason="refusal")
    monkeypatch.setattr(clinical_ai, "client_factory", lambda: declined)
    analysis = _analyse(ctx, ctx.rows[10]).json()["analysis"]
    assert analysis["engine"] == "fallback" and analysis["fallback_reason"] == "CLINICAL_AI_DECLINED"


def test_the_switch_off_skips_the_model_and_claims_without_a_note_are_refused(noted_run, monkeypatch):
    ctx = noted_run
    fake = FakeOllama(content=VERDICT.model_dump_json())
    _use_ollama(monkeypatch, fake)
    missing = _analyse(ctx, ctx.rows[20])
    assert missing.status_code == 409 and missing.json()["error"]["code"] == "CLINICAL_NOTE_MISSING"
    monkeypatch.setenv(clinical_ai.SWITCH_VARIABLE, "off")
    assert _analyse(ctx, ctx.rows[10]).json()["analysis"]["engine"] == "fallback"
    assert fake.calls == []


def test_fallback_reading_reports_only_plain_contradictions():
    base = {"claim_group": "K-1-17-III", "stay_days": 9, "secondary_diagnoses": ["E119"]}
    mild = clinical_ai.fallback_reading({**base, "clinical_note": "Kondisi ringan tanpa komplikasi. Dirawat 3 hari."})
    assert mild.verdict == "perlu_dicek" and len(mild.alasan) == 2
    clean = clinical_ai.fallback_reading({**base, "clinical_note": "Kondisi berat disertai komplikasi. Dirawat 9 hari."})
    assert clean.verdict == "sesuai" and "terbatas" in clean.ringkasan
    no_secondary = clinical_ai.fallback_reading({**base, "secondary_diagnoses": [], "clinical_note": "Dirawat 9 hari."})
    assert no_secondary.verdict == "perlu_dicek"


def test_requests_are_rate_limited_per_user(noted_run):
    ctx = noted_run
    statuses = [_analyse(ctx, ctx.rows[10]).status_code for _ in range(21)]
    assert statuses[:20] == [200] * 20 and statuses[20] == 429


def test_the_operator_cannot_ask_and_other_sources_are_never_read(noted_run, monkeypatch):
    ctx = noted_run
    fake = FakeOllama(content=VERDICT.model_dump_json())
    _use_ollama(monkeypatch, fake)
    denied = call(ctx.app, "POST", _note_url(ctx, ctx.rows[10], "clinical-analysis"), cookies=ctx.operator,
                  headers={"X-CSRF-Token": ctx.operator["cir_csrf"]})
    assert denied.status_code == 403
    # A file in the older synthetic column format: it is not the BPJS format, so nothing is read.
    batch, generated = import_batch(ctx.app, ctx.batch_db, ctx.operator)
    run_id = create_run(ctx.app, ctx.operator, batch["batch_id"]).json()["run"]["run_id"]
    case_id = generated.records[0]["case_id"]
    refused = call(ctx.app, "POST", f"/api/v1/runs/{run_id}/cases/{case_id}/clinical-analysis", cookies=ctx.verifier,
                   headers={"X-CSRF-Token": ctx.verifier["cir_csrf"]})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "CLINICAL_AI_SAMPLE_DATA_NOT_ALLOWED"
    assert fake.calls == []
