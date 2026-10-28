"""Build the demo claim files in the BPJS FKRTL column format (example data, never real rows).

1. demo-1-faskes-jujur.csv   honest hospitals only, including honest claims that look like fraud
                             (high-volume routine services, weekly scheduled therapy)
2. demo-2-kasus-kpk.csv      the same honest world plus one hospital that bills twice and raises the
                             INA-CBG severity of the same claims
3. demo-3-operasional.csv    a month of operations: under 2% fraud (10 hospitals) over six modes, plus honest lookalikes;
                             also written as one file per admission day under ``harian/`` for the drop folder

Realism without copying data: codes and their combinations are drawn from the aggregate tables stored in
the trained model (class -> INA-CBG, INA-CBG -> diagnosis, INA-CBG -> procedure, admission -> primary
diagnosis, median stay per INA-CBG and class of care; combinations seen fewer than 5 times were never kept).
Region and facility codes come from the exported category names. Participant numbers start with ``SYN``,
so the files can only ever be read as example data. Answer keys are written next to each CSV (never inside
it: the importer rejects label columns).

Every claim carries a short synthetic clinical note (``CATATAN_KLINIS``) with its own random vital signs and
laboratory values. Fraud modes leave traces in the note the way they would in a real record: a cloned claim
copies another patient's note word for word, an upcoded claim keeps a mild "tanpa komplikasi" note under a
severity III INA-CBG, a prolonged stay keeps the note of the original shorter stay, and a split readmission
says it continues the earlier admission.

Secondary diagnoses (``FKL24``, codes separated by ";") follow the 2024 sample: about 38% of severity I
inpatient claims have one or two, severity II and III claims almost always one to four. An upcoded claim keeps
the secondary diagnoses of its original severity; 40% of upcoders also add one invented code, so the
severity-without-secondary check is not built to catch every upcoding. Special top-up codes (FKL33/35/38/41/44)
of honest claims are drawn from the INA-CBG x special-code pairs of the reference (special_reference.json);
the special top-up fraud mode attaches a special code to INA-CBGs it never accompanies there.

Usage: python -m scripts.make_bpjs_demo_datasets --out ../demo-data [--check]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.analytics.ml_model import DEFAULT_MODEL_DIR, MODEL_DIR_VARIABLE, category_labels
from app.data_sources.bpjs_csv import UPLOAD_PSEUDONYM_SECRET
from app.data_sources.bpjs_fkrtl_adapter import pseudonymous_case_id

COLUMNS = ("PSTV01", "FKL02", "FKL03", "FKL04", "FKL05", "FKL06", "FKL07", "FKL08", "FKL09", "FKL13",
           "FKL16", "FKL18", "FKL19", "FKL30", "FKL31", "FKL32", "FKL33", "FKL35", "FKL38", "FKL41", "FKL44",
           "FKL47", "FKL24", "CATATAN_KLINIS")
SPECIAL_COLUMN = {"SA": "FKL33", "YY": "FKL35", "RR": "FKL38", "II": "FKL41", "DD": "FKL44"}
# Share of inpatient claims with at least one secondary diagnosis, and how many, by severity (2024 sample).
SECONDARY_BY_SEVERITY = {"0": (0.38, 1, 2), "I": (0.38, 1, 2), "II": (0.998, 1, 3), "III": (0.9996, 2, 4)}
DEMOS = ("demo-1-faskes-jujur", "demo-2-kasus-kpk", "demo-3-operasional")
MISSING = "__missing__"
SEP = "\x1f"
START = date(2024, 9, 2)
# INA-CBG: <CMG>-<case type>-<number>-<severity>; case types 1, 4 and 6 are inpatient.
CBG = re.compile(r"^([A-Z])-(\d)-(\d{2})-(0|I|II|III)$")
INPATIENT_TYPES = {"1", "4", "6"}
SEVERITY_UP = {"I": ("II", "III"), "II": ("III",)}
HOSPITAL_CLASSES = ("1", "2", "3", "4", "5", "6", "7")
OWNERSHIP = ("2", "3", "9", "9", "8")
COMPLAINTS = ("demam", "nyeri perut", "sesak napas", "batuk berdahak", "nyeri dada", "mual dan muntah", "lemas",
              "pusing berputar", "nyeri pinggang", "diare", "bengkak pada tungkai", "nyeri sendi")
SEVERITY_TEXT = {
    "I": "Kondisi ringan tanpa komplikasi dan tanpa komorbid berarti.",
    "II": "Kondisi sedang dengan komorbid yang terkontrol.",
    "III": "Kondisi berat disertai komplikasi dan komorbid yang memerlukan pemantauan ketat.",
    "0": "Kondisi stabil.",
}
OUTPATIENT_PLAN = ("Diberikan terapi obat oral dan edukasi.", "Dilakukan tindakan sesuai indikasi, pasien pulang.",
                   "Terapi dilanjutkan, kontrol ulang dua minggu lagi.", "Dirujuk balik ke faskes pertama setelah stabil.")


def _model_dir() -> Path:
    import os
    return Path(os.environ.get(MODEL_DIR_VARIABLE) or DEFAULT_MODEL_DIR)


class Vocabulary:
    """Weighted code combinations from the trained model's aggregate tables."""

    def __init__(self) -> None:
        reference = json.loads((_model_dir() / "reference.json").read_text(encoding="utf-8"))
        self.labels = category_labels()
        if not self.labels:
            raise SystemExit("category_labels.json tidak ada; jalankan python -m scripts.export_category_labels")
        pairs = reference["pair_counts"]

        def table(name: str) -> dict[str, tuple[list[str], list[int]]]:
            grouped: dict[str, Counter[str]] = defaultdict(Counter)
            for key, count in pairs[name].items():
                first, second = key.split(SEP)
                grouped[first][second] += count
            return {key: (list(values), list(values.values())) for key, values in grouped.items()}

        by_class = table("facility_class__claim_group")
        self.cbg_by_class = {klass: (codes, weights) for klass, (codes, weights) in by_class.items()
                             if klass in HOSPITAL_CLASSES and sum(c != MISSING and CBG.match(c) is not None for c in codes) >= 40}
        procedures = table("claim_group__procedure_code")
        self.procedure_by_cbg = procedures
        dx_cbg: dict[str, Counter[str]] = defaultdict(Counter)
        for key, count in pairs["primary_diagnosis__claim_group"].items():
            diagnosis, group = key.split(SEP)
            if diagnosis != MISSING:
                dx_cbg[group][diagnosis] += count
        self.dx_by_cbg = {key: (list(values), list(values.values())) for key, values in dx_cbg.items()}
        self.admission_by_primary: dict[str, tuple[list[str], list[int]]] = {}
        adm: dict[str, Counter[str]] = defaultdict(Counter)
        for key, count in pairs["admission_diagnosis__primary_diagnosis"].items():
            admission, primary = key.split(SEP)
            if admission != MISSING:
                adm[primary][admission] += count
        self.admission_by_primary = {key: (list(values), list(values.values())) for key, values in adm.items()}
        self.stay: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        for key, (center, spread) in reference["stay_peer_fine"].items():
            group, care = key.split("|")
            self.stay[group].append((care, center, spread))
        self.stay_coarse = {key: tuple(value) for key, value in reference["stay_peer_coarse"].items()}
        self.known_cbg = {code for codes, _ in self.dx_by_cbg.values() for code in codes} | set(self.dx_by_cbg)
        provinces = sorted(code for code in self.labels["province_code"] if code != "99")
        # Special top-ups: per INA-CBG, the codes it accompanies and the chance a claim of that INA-CBG has one.
        special_path = _model_dir() / "special_reference.json"
        special = json.loads(special_path.read_text(encoding="utf-8")) if special_path.is_file() else {}
        group_rows = Counter()
        for key, count in pairs["primary_diagnosis__claim_group"].items():
            group_rows[key.split(SEP)[1]] += count
        reference_rows = sum(group_rows.values()) or 1
        self.special_by_cbg: dict[str, tuple[list[str], list[int], float]] = {}
        for key, count in (special.get("pairs") or {}).items():
            group, code = key.split(SEP)
            codes, weights, _ = self.special_by_cbg.setdefault(group, ([], [], 0.0))
            codes.append(code)
            weights.append(count)
        for group, (codes, weights, _) in list(self.special_by_cbg.items()):
            expected = group_rows.get(group, 0) / reference_rows * max(special.get("claims", 0), 1)
            self.special_by_cbg[group] = (codes, weights, min(0.9, sum(weights) / expected) if expected else 0.0)
        self.special_codes = sorted({code for codes, _, _ in self.special_by_cbg.values() for code in codes})
        self.secondary_codes = sorted(self.admission_by_primary)
        self.municipalities = defaultdict(list)
        for code in sorted(self.labels["municipality_code"]):
            if code[:2] in provinces:
                self.municipalities[code[:2]].append(code)


class World:
    """Hospitals, returning patients and a claim factory; every row is BPJS-format example data."""

    def __init__(self, seed: int, hospitals: int, vocabulary: Vocabulary, id_base: int = 0):
        self.rng = random.Random(seed)
        self.vocab = vocabulary
        self.rows: list[dict[str, str]] = []
        self.labels: dict[str, str] = {}  # case reference -> scenario or honest_* lookalike
        # Each demo world has its own participant and visit number range, so files of different
        # worlds never look like the same patient when the cross-day checks compare them.
        self.next_patient = id_base * 10_000_000 + 1
        self.next_visit = id_base * 100_000_000 + 1
        self.last_visit: dict[str, date] = {}
        provinces = [code for code in sorted(vocabulary.municipalities) if len(vocabulary.municipalities[code]) >= 4]
        # The first 15 hospitals share five provinces (several hospitals of one class per province, so the
        # regional comparison has class peers); the others spread over twelve more provinces, as a national
        # claim file would.
        chosen = self.rng.sample(provinces, min(17, len(provinces)))
        anchors, spread = chosen[:5], chosen[5:] or chosen[:5]
        classes = sorted(vocabulary.cbg_by_class)
        self.hospitals: list[dict[str, Any]] = []
        used: set[str] = set()
        for index in range(hospitals):
            province = anchors[index % len(anchors)] if index < 15 else spread[(index - 15) % len(spread)]
            municipality = self.rng.choice([code for code in vocabulary.municipalities[province] if code not in used])
            used.add(municipality)
            # Several hospitals of one class per province (as in the sample), so a hospital has class peers nearby.
            klass = classes[(index // 15) % len(classes)]
            self.hospitals.append({
                "FKL05": province, "FKL06": municipality, "FKL07": OWNERSHIP[index % len(OWNERSHIP)], "FKL08": "1",
                "FKL09": klass, "FKL31": str(1 + index % 5), "patients": [],
                "weight": {"1": 3.0, "2": 2.4, "5": 2.0, "6": 1.6, "3": 1.3, "7": 1.0, "4": 0.8}.get(klass, 1.0),
            })

    # ---- codes
    def _pick(self, table: tuple[list[str], list[int]]) -> str:
        codes, weights = table
        return self.rng.choices(codes, weights)[0]

    def codes(self, hospital: dict[str, Any]) -> dict[str, str]:
        while True:
            group = self._pick(self.vocab.cbg_by_class[hospital["FKL09"]])
            if group == MISSING or not CBG.match(group) or group not in self.vocab.dx_by_cbg:
                continue
            primary = self._pick(self.vocab.dx_by_cbg[group])
            admission = self._pick(self.vocab.admission_by_primary[primary]) \
                if primary in self.vocab.admission_by_primary else primary
            procedure = self._pick(self.vocab.procedure_by_cbg[group]) if group in self.vocab.procedure_by_cbg else MISSING
            peers = self.vocab.stay.get(group) or [("3", *self.vocab.stay_coarse.get(group, (0.0, 0.0)))]
            care, center, spread = self.rng.choice(peers)
            return {"FKL19": group, "FKL18": primary, "FKL16": admission,
                    "FKL30": "" if procedure == MISSING else procedure, "FKL13": care,
                    "stay": str(max(0, round(self.rng.gauss(center, max(spread, 0.5) * 0.8))) if center else 0)}

    def tariff(self, group: str) -> int:
        match = CBG.match(group)
        local = random.Random(group)
        if match is None:
            return local.randrange(150, 400) * 1000
        _cmg, case_type, _number, severity = match.groups()
        if case_type in INPATIENT_TYPES:
            base = local.randrange(3_000, 9_000) * 1000
            return int(base * {"I": 1.0, "II": 1.5, "III": 2.2, "0": 1.0}[severity])
        return local.randrange(150, 450) * 1000

    # ---- claims
    def patient(self, hospital: dict[str, Any], day: date | None = None) -> str:
        """A returning patient (never twice on the same day by chance) or a new one."""
        if hospital["patients"] and self.rng.random() < 0.25:
            token = self.rng.choice(hospital["patients"])
            if day is None or self.last_visit.get(token) != day:
                return token
        token = f"SYN{self.next_patient:08d}"
        self.next_patient += 1
        hospital["patients"].append(token)
        return token

    def add(self, hospital: dict[str, Any], day: date, *, patient: str | None = None,
            codes: dict[str, str] | None = None, label: str | None = None, stay: int | None = None,
            note_from: dict[str, str] | None = None, note_kind: str = "honest") -> dict[str, str]:
        codes = dict(codes or self.codes(hospital))
        length = int(codes.pop("stay")) if stay is None else stay
        row = {
            "PSTV01": patient or self.patient(hospital, day), "FKL02": f"SYNV{self.next_visit:09d}",
            "FKL03": day.isoformat(), "FKL04": (day + timedelta(days=length)).isoformat(),
            **{key: hospital[key] for key in ("FKL05", "FKL06", "FKL07", "FKL08", "FKL09", "FKL31")},
            "FKL32": "1", **codes, "FKL47": str(self.tariff(codes["FKL19"])),
        }
        match = CBG.match(codes["FKL19"])
        # Facts for the note (written last, by write_notes): the stay and severity as first recorded.
        row["_stay"], row["_severity"], row["_note_kind"] = length, match.group(4) if match else "0", note_kind
        row["FKL24"] = self.secondary(row["_severity"]) if match and match.group(2) in INPATIENT_TYPES else ""
        for column in SPECIAL_COLUMN.values():
            row[column] = ""
        honest = self.vocab.special_by_cbg.get(codes["FKL19"])
        if honest and self.rng.random() < honest[2]:
            code = self.rng.choices(honest[0], honest[1])[0]
            row[SPECIAL_COLUMN.get(code[:2], "FKL35")] = code
        if note_from is not None:
            row["_note_from"] = note_from  # type: ignore[assignment]
        self.next_visit += 1
        self.last_visit[row["PSTV01"]] = day
        self.rows.append(row)
        if label:
            self.labels[case_reference(row)] = label
        return row

    def honest_month(self, days: int, claims_per_day: int) -> None:
        weights = [hospital["weight"] for hospital in self.hospitals]
        for offset in range(days):
            day = START + timedelta(days=offset)
            for _ in range(claims_per_day):
                self.add(self.rng.choices(self.hospitals, weights)[0], day)

    # ---- honest claims that look like fraud
    def routine_high_volume(self, hospital: dict[str, Any], days: int, per_day: int) -> None:
        """Many different patients with the same common outpatient package on the same day (e.g. dialysis)."""
        routine = Counter((row["FKL19"], row["FKL18"], row["FKL16"], row["FKL30"]) for row in self.rows
                          if row["FKL06"] == hospital["FKL06"] and row["FKL03"] == row["FKL04"])
        group, primary, admission, procedure = routine.most_common(1)[0][0]
        for offset in range(days):
            for _ in range(per_day):
                self.add(hospital, START + timedelta(days=offset), patient=self.patient(hospital), stay=0,
                         codes={"FKL19": group, "FKL18": primary, "FKL16": admission, "FKL30": procedure,
                                "FKL13": "3", "stay": "0"}, label="honest_routine_high_volume")

    def scheduled_therapy(self, hospital: dict[str, Any], patients: int, weeks: int) -> None:
        """The same patient returns every week for the same outpatient therapy."""
        outpatient = [row for row in self.rows if row["FKL06"] == hospital["FKL06"] and row["FKL03"] == row["FKL04"]]
        for _ in range(patients):
            template = self.rng.choice(outpatient)
            token, first = self.patient(hospital), self.rng.randrange(7)
            for week in range(weeks):
                self.add(hospital, START + timedelta(days=first + 7 * week), patient=token, stay=0, codes={
                    key: template[key] for key in ("FKL19", "FKL18", "FKL16", "FKL30", "FKL13")} | {"stay": "0"},
                    label="honest_scheduled_therapy")

    # ---- fraud modes
    def _codes_of(self, row: dict[str, str]) -> dict[str, str]:
        return {key: row[key] for key in ("FKL19", "FKL18", "FKL16", "FKL30", "FKL13")}

    def repeat_billing(self, row: dict[str, str]) -> None:
        """The same visit billed again: same patient, admission day and codes, a new visit number."""
        hospital = self._hospital_of(row)
        stay = (date.fromisoformat(row["FKL04"]) - date.fromisoformat(row["FKL03"])).days
        self.add(hospital, date.fromisoformat(row["FKL03"]), patient=row["PSTV01"], codes=self._codes_of(row) | {"stay": "0"},
                 stay=stay, label="repeat_billing", note_from=row)

    def upcode(self, row: dict[str, str], label: str = "upcoding") -> bool:
        """Raise the INA-CBG severity of an inpatient claim while the diagnosis and stay stay mild."""
        match = CBG.match(row["FKL19"])
        if match is None or match.group(4) not in SEVERITY_UP:
            return False
        options = [f"{match.group(1)}-{match.group(2)}-{match.group(3)}-{level}" for level in SEVERITY_UP[match.group(4)]]
        options = [code for code in options if code in self.vocab.known_cbg]
        if not options:
            return False
        old = case_reference(row)
        row["FKL19"] = options[-1]
        row["FKL47"] = str(self.tariff(row["FKL19"]))
        if not row.get("FKL24") and self.rng.random() < 0.4:
            row["FKL24"] = self.rng.choice(self.vocab.secondary_codes)
        self.labels[old] = label
        return True

    def prolong_stay(self, row: dict[str, str]) -> bool:
        """Keep an inpatient far longer than claims of the same INA-CBG and class of care."""
        match = CBG.match(row["FKL19"])
        if match is None or match.group(2) not in INPATIENT_TYPES:
            return False
        peers = {care: (center, spread) for care, center, spread in self.vocab.stay.get(row["FKL19"], [])}
        center, spread = peers.get(row["FKL13"], self.vocab.stay_coarse.get(row["FKL19"], (4.0, 2.0)))
        # 5 to 14 extra days: not tuned to any check's threshold, so some are caught and some are not.
        row["FKL04"] = (date.fromisoformat(row["FKL03"]) + timedelta(days=int(center) + self.rng.randint(5, 14))).isoformat()
        self.labels[case_reference(row)] = "prolonged_stay"
        return True

    def readmission_split(self, row: dict[str, str], extra: int = 2) -> bool:
        """One episode split into short admissions days apart, each billed separately."""
        match = CBG.match(row["FKL19"])
        if match is None or match.group(2) not in INPATIENT_TYPES:
            return False
        hospital, discharge = self._hospital_of(row), date.fromisoformat(row["FKL04"])
        for _ in range(extra):
            day = discharge + timedelta(days=self.rng.randrange(1, 3))
            new = self.add(hospital, day, patient=row["PSTV01"], codes=self._codes_of(row) | {"stay": "0"},
                           stay=self.rng.randrange(1, 3), label="readmission_split", note_kind="readmit")
            discharge = date.fromisoformat(new["FKL04"])
        return True

    def cloning(self, row: dict[str, str], copies: int) -> None:
        """A claim template copied to other patients on the same day."""
        hospital = self._hospital_of(row)
        stay = (date.fromisoformat(row["FKL04"]) - date.fromisoformat(row["FKL03"])).days
        for _ in range(copies):
            self.add(hospital, date.fromisoformat(row["FKL03"]), codes=self._codes_of(row) | {"stay": "0"},
                     stay=stay, label="cloning", note_from=row)

    def secondary(self, severity: str) -> str:
        share, low, high = SECONDARY_BY_SEVERITY[severity]
        if self.rng.random() >= share:
            return ""
        return ";".join(sorted(set(self.rng.sample(self.vocab.secondary_codes, self.rng.randint(low, high)))))

    def special_topup(self, row: dict[str, str]) -> bool:
        """Bill a special drug/prosthesis/procedure with an INA-CBG it never accompanies in the reference."""
        paired = set(self.vocab.special_by_cbg.get(row["FKL19"], ([], [], 0))[0])
        options = [code for code in self.vocab.special_codes if code not in paired]
        if not options or any(row[column] for column in SPECIAL_COLUMN.values()):
            return False
        code = self.rng.choice(options)
        row[SPECIAL_COLUMN.get(code[:2], "FKL35")] = code
        self.labels[case_reference(row)] = "special_topup"
        return True

    # ---- clinical notes
    def note(self, row: dict[str, str]) -> str:
        """A synthetic note from the row as first recorded; each note gets its own vital signs and labs."""
        rng = random.Random(row["FKL02"])
        inpatient = int(row["_stay"]) > 0  # type: ignore[arg-type]
        parts = [
            "Lanjutan perawatan dari rawat inap beberapa hari sebelumnya dengan keluhan yang sama." if row["_note_kind"] == "readmit" else "",
            f"{rng.choice(('Laki-laki', 'Perempuan'))} {rng.randint(18, 85)} tahun datang dengan keluhan "
            f"{rng.choice(COMPLAINTS)} sejak {rng.randint(1, 10)} hari.",
            f"TD {rng.randint(100, 165)}/{rng.randint(60, 100)} mmHg, nadi {rng.randint(60, 112)} x/menit, "
            f"suhu {rng.uniform(36.2, 38.9):.1f} C, SpO2 {rng.randint(92, 99)}%.",
            f"Diagnosis kerja {row['FKL18'] or '-'}.",
        ]
        if inpatient:
            parts += [SEVERITY_TEXT[row["_severity"]],  # type: ignore[index]
                      f"Hb {rng.uniform(9.5, 15.5):.1f} g/dL, leukosit {rng.uniform(4.5, 16.0):.1f} ribu/uL.",
                      f"Dirawat {row['_stay']} hari, pulang dengan kondisi membaik."]
        else:
            parts.append(rng.choice(OUTPATIENT_PLAN))
        return " ".join(part for part in parts if part)

    def copy_details(self) -> None:
        """Copied claims (cloning, repeat billing) carry their source's secondary diagnoses and special codes."""
        for row in self.rows:
            source = row.get("_note_from")
            if source is not None:
                for column in ("FKL24", *SPECIAL_COLUMN.values()):
                    row[column] = source[column]  # type: ignore[index]

    def write_notes(self) -> None:
        """Fill CATATAN_KLINIS; copied claims (cloning, repeat billing) take their source's note verbatim."""
        for row in self.rows:
            if "_note_from" not in row:
                row["CATATAN_KLINIS"] = self.note(row)
        for row in self.rows:
            if "_note_from" in row:
                row["CATATAN_KLINIS"] = row["_note_from"]["CATATAN_KLINIS"]  # type: ignore[index]

    def _hospital_of(self, row: dict[str, str]) -> dict[str, Any]:
        return next(hospital for hospital in self.hospitals if hospital["FKL06"] == row["FKL06"])

    def inpatient_rows(self, hospital: dict[str, Any] | None = None) -> list[dict[str, str]]:
        return [row for row in self.rows if row["FKL03"] != row["FKL04"] and row["PSTV01"].startswith("SYN")
                and case_reference(row) not in self.labels and (hospital is None or row["FKL06"] == hospital["FKL06"])]


def case_reference(row: dict[str, str]) -> str:
    """The case reference the importer will give this row."""
    return pseudonymous_case_id(row["PSTV01"], row["FKL02"], secret=UPLOAD_PSEUDONYM_SECRET)


def build(name: str, vocabulary: Vocabulary | None = None) -> World:
    world = _build(name, vocabulary or Vocabulary())
    world.copy_details()
    world.write_notes()
    return world


def _build(name: str, vocabulary: Vocabulary) -> World:
    if name == "demo-1-faskes-jujur":
        world = World(101, 24, vocabulary, id_base=1)
        world.honest_month(14, 820)
        world.routine_high_volume(world.hospitals[0], 14, 12)
        world.scheduled_therapy(world.hospitals[1], 25, 2)
        return world
    if name == "demo-2-kasus-kpk":
        world = World(202, 24, vocabulary, id_base=2)
        suspect = world.hospitals[5]
        suspect["weight"] = 3.0
        world.honest_month(14, 820)
        world.routine_high_volume(world.hospitals[0], 14, 12)
        world.scheduled_therapy(world.hospitals[1], 25, 2)
        rows = world.inpatient_rows(suspect)
        world.rng.shuffle(rows)
        upcoded = [row for row in rows[: int(len(rows) * 0.6)] if world.upcode(row, "repeat_billing")]
        for row in upcoded[: int(len(upcoded) * 0.7)]:
            world.repeat_billing(row)
        for row in rows[int(len(rows) * 0.6): int(len(rows) * 0.8)]:
            world.prolong_stay(row)
        # Outpatient visits billed twice as well (visits with a recorded procedure can be compared).
        outpatient = [row for row in world.rows if row["FKL06"] == suspect["FKL06"] and row["FKL03"] == row["FKL04"]
                      and row["FKL30"] and case_reference(row) not in world.labels]
        for row in world.rng.sample(outpatient, len(outpatient) // 6):
            world.labels[case_reference(row)] = "repeat_billing"
            world.repeat_billing(row)
        return world
    if name == "demo-3-operasional":
        world = World(303, 40, vocabulary, id_base=3)
        world.honest_month(28, 1000)
        world.routine_high_volume(world.hospitals[0], 28, 10)
        world.routine_high_volume(world.hospitals[2], 28, 8)
        world.scheduled_therapy(world.hospitals[1], 40, 4)
        fraud_hospitals = world.hospitals[5:13]
        for index, hospital in enumerate(fraud_hospitals):
            rows = world.inpatient_rows(hospital)
            world.rng.shuffle(rows)
            take = rows[: max(40, len(rows) // 4)]
            mode = index % 4
            for row in take:
                if mode == 0:
                    if world.upcode(row, "repeat_billing"):
                        world.repeat_billing(row)
                elif mode == 1:
                    world.upcode(row)
                elif mode == 2:
                    world.prolong_stay(row)
                else:
                    world.readmission_split(row)
        for row in world.rng.sample(world.inpatient_rows(world.hospitals[13]), 12):
            world.cloning(row, 6)
        # Special top-ups (cataract surgery, MRI, haemophilia drugs) are mostly outpatient: any claim of the hospital.
        topup = [row for row in world.rows if row["FKL06"] == world.hospitals[14]["FKL06"] and case_reference(row) not in world.labels]
        world.rng.shuffle(topup)
        for row in topup[:60]:
            world.special_topup(row)
        return world
    raise SystemExit(f"Demo tidak dikenal: {name}")


def to_csv(rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(COLUMNS), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def check(world: World) -> dict[str, Any]:
    """Analyse the file exactly as an upload and summarise the story (lanes per label, top facility groups)."""
    from app.analytics.action_policy import get_action_policy_config
    from app.data_sources.bpjs_csv import BPJS_CSV_MAPPING_VERSION, BPJS_CSV_SCHEMA_VERSION, parse_bpjs_csv
    from app.data_sources.providers import SyntheticBatchProvider
    from app.services.provider_orchestrator import execute_provider_snapshot

    records, _summary = parse_bpjs_csv(to_csv(world.rows), max_rows=200_000)
    batch = {"source_type": "synthetic_csv", "schema_version": BPJS_CSV_SCHEMA_VERSION, "mapping_version": BPJS_CSV_MAPPING_VERSION,
             "status": "ready", "batch_version": 1, "content_checksum": "0" * 64}
    _, snapshot = execute_provider_snapshot(SyntheticBatchProvider(batch=batch, normalized_records=records), get_action_policy_config())
    lanes = {case_id: item["lane"] for case_id, item in snapshot["action_policy"]["cases"].items()}
    ml_items = {item["case_id"] for item in (snapshot.get("ml_anomaly") or {}).get("items", [])}
    by_label: dict[str, Counter[str]] = defaultdict(Counter)
    for case_id, label in world.labels.items():
        by_label[label][lanes.get(case_id, "ai_list" if case_id in ml_items else "not_flagged")] += 1
    groups = (snapshot.get("facility_groups") or {}).get("groups", [])
    return {
        "claims": len(world.rows), "lanes": dict(Counter(lanes.values())),
        "by_label": {label: dict(counts) for label, counts in sorted(by_label.items())},
        "top_groups": [{key: group.get(key) for key in ("title", "region", "level", "lane_counts", "claims")} for group in groups[:4]],
        "ai_mode": (snapshot.get("ml_anomaly") or {}).get("mode"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--only", choices=DEMOS)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    vocabulary = Vocabulary()
    for name in [args.only] if args.only else DEMOS:
        world = build(name, vocabulary)
        (args.out / f"{name}.csv").write_bytes(to_csv(world.rows))
        (args.out / f"{name}.answers.json").write_text(json.dumps(
            {"description": "Kunci jawaban data contoh: referensi kasus -> skenario (bukan untuk diunggah).",
             "labels": world.labels}, indent=0, sort_keys=True), encoding="utf-8")
        if name == "demo-3-operasional":
            daily = args.out / "harian"
            daily.mkdir(exist_ok=True)
            for stale in daily.glob("klaim-*.csv"):  # days of an earlier build must not linger
                stale.unlink()
            by_day: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in world.rows:
                by_day[row["FKL03"]].append(row)
            for day, rows in sorted(by_day.items()):
                (daily / f"klaim-{day}.csv").write_bytes(to_csv(rows))
        print(name, len(world.rows), "klaim", Counter(world.labels.values()))
        if args.check:
            print(json.dumps(check(world), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
