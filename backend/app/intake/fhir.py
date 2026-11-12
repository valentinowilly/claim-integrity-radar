"""HL7 FHIR (R4) claim bundles, as exchanged with RME/SATUSEHAT-integrated systems, to canonical claim rows.

One ``collection`` Bundle may hold many claims. Each claim is an Encounter with its Patient, Organization,
Conditions, Procedure, Claim (INA-CBG group, billed total, special top-ups), Composition (resume medis) and
DocumentReferences (supporting documents). The mapping reads only these resources and fields; anything it does
not recognise is ignored. Code systems that carry BPJS-specific values (INA-CBG, top-up codes, facility
attributes) use this project's own namespace, never an official URL, because the national profiles are not
public in this form.

``rows_to_bundle`` is the inverse used to build example files and tests.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

NS = "https://claim-integrity-radar.local/fhir"
SYS_PARTICIPANT = f"{NS}/sid/nomor-kartu"
SYS_VISIT = f"{NS}/sid/nomor-kunjungan"
SYS_FACILITY = f"{NS}/sid/kode-faskes"
SYS_ICD10 = "http://hl7.org/fhir/sid/icd-10"
SYS_ICD9CM = "http://hl7.org/fhir/sid/icd-9-cm"
SYS_INACBG = f"{NS}/CodeSystem/ina-cbg"
SYS_TOPUP = f"{NS}/CodeSystem/topup-khusus"
SYS_SERVICE = f"{NS}/CodeSystem/jenis-layanan"
SYS_EVIDENCE = f"{NS}/CodeSystem/jenis-bukti"
EXT = f"{NS}/StructureDefinition"
FACILITY_EXTENSIONS = {  # Organization attributes recorded in the claim export
    "provinsi": "FKL05", "kabupaten-kota": "FKL06", "kepemilikan": "FKL07", "jenis-faskes": "FKL08",
    "kelas-faskes": "FKL09", "kapasitas-harian": "KAPASITAS_HARIAN",
}
CLAIM_EXTENSIONS = {"kelas-rawat": "FKL13", "regional-tarif": "FKL31", "kelompok-tarif": "FKL32",
                    "jumlah-layanan": "JUMLAH_LAYANAN"}
TOPUP_COLUMNS = ("FKL33", "FKL35", "FKL38", "FKL41", "FKL44")


class FhirReadError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _ext(url: str, value: str) -> dict[str, Any]:
    return {"url": f"{EXT}/{url}", "valueString": value}


def _ext_value(resource: dict[str, Any], name: str) -> str | None:
    for item in resource.get("extension") or []:
        if item.get("url") == f"{EXT}/{name}":
            value = item.get("valueString")
            return str(value) if value not in (None, "") else None
    return None


def _identifier(resource: dict[str, Any], system: str) -> str | None:
    for item in resource.get("identifier") or []:
        if item.get("system") == system and item.get("value"):
            return str(item["value"])
    return None


def _code(concept: dict[str, Any] | None, system: str) -> str | None:
    for coding in (concept or {}).get("coding") or []:
        if coding.get("system") == system and coding.get("code"):
            return str(coding["code"])
    return None


def _date(value: str | None) -> str | None:
    return value[:10] if value else None


def _time(value: str | None) -> str | None:
    return value[11:16] if value and len(value) >= 16 and value[10] == "T" else None


def bundle_to_rows(bundle: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Canonical rows (column name -> text) of every Encounter in the bundle, plus a short summary."""
    if isinstance(bundle, (bytes, str)):
        try:
            bundle = json.loads(bundle)
        except (ValueError, UnicodeDecodeError) as exc:
            raise FhirReadError("FHIR_INVALID_JSON") from exc
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise FhirReadError("FHIR_NOT_A_BUNDLE")
    by_ref: dict[str, dict[str, Any]] = {}
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in bundle.get("entry") or []:
        resource = (entry or {}).get("resource") or {}
        kind = resource.get("resourceType")
        if not kind:
            continue
        if resource.get("id"):
            by_ref[f"{kind}/{resource['id']}"] = resource
        if entry.get("fullUrl"):
            by_ref[entry["fullUrl"]] = resource
        by_type[kind].append(resource)

    def ref(reference: dict[str, Any] | None) -> dict[str, Any]:
        return by_ref.get((reference or {}).get("reference") or "", {})

    def encounter_of(item: dict[str, Any]) -> str | None:
        if item.get("resourceType") == "DocumentReference":
            linked = (item.get("context") or {}).get("encounter") or [{}]
            return (linked[0] or {}).get("reference")
        return (item.get("encounter") or {}).get("reference")

    linked: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for kind in ("Procedure", "Composition", "DocumentReference"):
        for item in by_type[kind]:
            linked[(kind, encounter_of(item) or "")].append(item)

    def about(kind: str, encounter_ref: str) -> list[dict[str, Any]]:
        return linked[(kind, encounter_ref)]

    claims_of: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in by_type["Claim"]:
        for reference in {((entry.get("encounter") or [{}])[0] or {}).get("reference") for entry in claim.get("item") or []}:
            if reference:
                claims_of[reference].append(claim)

    rows: list[dict[str, str]] = []
    skipped = 0
    for encounter in by_type["Encounter"]:
        encounter_ref = f"Encounter/{encounter.get('id')}"
        patient = ref(encounter.get("subject"))
        organization = ref(encounter.get("serviceProvider"))
        row: dict[str, str | None] = {
            "PSTV01": _identifier(patient, SYS_PARTICIPANT),
            "FKL02": _identifier(encounter, SYS_VISIT),
            "FKL03": _date((encounter.get("period") or {}).get("start")),
            "FKL04": _date((encounter.get("period") or {}).get("end")),
            "ID_FASKES": _identifier(organization, SYS_FACILITY),
            "JAM_LAYANAN": _time((encounter.get("period") or {}).get("start")),
            "JENIS_LAYANAN": _code((encounter.get("serviceType") or None), SYS_SERVICE),
        }
        for name, column in FACILITY_EXTENSIONS.items():
            row[column] = _ext_value(organization, name)
        secondary: list[str] = []
        for diagnosis in encounter.get("diagnosis") or []:
            condition = ref(diagnosis.get("condition"))
            code = _code(condition.get("code"), SYS_ICD10)
            use = _code(diagnosis.get("use"), "http://terminology.hl7.org/CodeSystem/diagnosis-role")
            if not code:
                continue
            if use == "AD":
                row["FKL16"] = code
            elif diagnosis.get("rank") == 1 or use == "DD":
                row["FKL18"] = code
            else:
                secondary.append(code)
        row["FKL24"] = ";".join(secondary) or None
        procedures = about("Procedure", encounter_ref)
        row["FKL30"] = next((_code(item.get("code"), SYS_ICD9CM) for item in procedures if _code(item.get("code"), SYS_ICD9CM)), None)
        claims = claims_of.get(encounter_ref, [])
        if claims:
            claim = claims[0]
            for name, column in CLAIM_EXTENSIONS.items():
                row[column] = _ext_value(claim, name)
            total = (claim.get("total") or {}).get("value")
            row["FKL47"] = str(int(total)) if isinstance(total, (int, float)) else None
            for item in claim.get("item") or []:
                group = _code(item.get("productOrService"), SYS_INACBG)
                if group:
                    row["FKL19"] = group
                for column in TOPUP_COLUMNS:
                    code = _code(item.get("productOrService"), f"{SYS_TOPUP}/{column}")
                    if code:
                        row[column] = code
        compositions = about("Composition", encounter_ref)
        if compositions:
            sections = compositions[0].get("section") or []
            texts = [((section.get("text") or {}).get("div") or "") for section in sections]
            note = " ".join(_strip_div(text) for text in texts if text).strip()
            row["CATATAN_KLINIS"] = note or None
        documents = about("DocumentReference", encounter_ref)
        evidence = sorted({code for item in documents for code in [_code(item.get("type"), SYS_EVIDENCE)] if code})
        row["BUKTI_TERCATAT"] = ";".join(evidence) or None
        if not row["PSTV01"] or not row["FKL02"] or not row["FKL03"]:
            skipped += 1
            continue
        rows.append({key: value for key, value in row.items() if value not in (None, "")})
    return rows, {"encounters": len(by_type["Encounter"]), "claims": len(rows), "skipped": skipped,
                  "documents": len(by_type["DocumentReference"]), "compositions": len(by_type["Composition"])}


def _strip_div(div: str) -> str:
    import html
    import re

    return html.unescape(re.sub(r"<[^>]+>", " ", div)).replace("\xa0", " ").strip()


def rows_to_bundle(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Example bundle with one Encounter (and its resources) per canonical row."""
    import html

    entries: list[dict[str, Any]] = []
    organizations: dict[str, str] = {}
    patients: dict[str, str] = {}

    def add(resource: dict[str, Any]) -> str:
        reference = f"{resource['resourceType']}/{resource['id']}"
        entries.append({"fullUrl": reference, "resource": resource})
        return reference

    for index, row in enumerate(rows):
        key = f"{index:06d}"
        participant = row["PSTV01"]
        if participant not in patients:
            patients[participant] = add({"resourceType": "Patient", "id": f"p{len(patients):06d}",
                                         "identifier": [{"system": SYS_PARTICIPANT, "value": participant}]})
        facility_key = row.get("ID_FASKES") or "|".join(row.get(column) or "" for column in FACILITY_EXTENSIONS.values())
        if facility_key not in organizations:
            organization: dict[str, Any] = {"resourceType": "Organization", "id": f"o{len(organizations):04d}",
                                            "extension": [_ext(name, row[column]) for name, column in FACILITY_EXTENSIONS.items()
                                                          if row.get(column)]}
            if row.get("ID_FASKES"):
                organization["identifier"] = [{"system": SYS_FACILITY, "value": row["ID_FASKES"]}]
            organizations[facility_key] = add(organization)
        start = row["FKL03"] + (f"T{row['JAM_LAYANAN']}:00+07:00" if row.get("JAM_LAYANAN") else "")
        diagnoses = []
        for role, column, rank in (("AD", "FKL16", 2), ("DD", "FKL18", 1)):
            if row.get(column):
                condition = add({"resourceType": "Condition", "id": f"c{key}{role}",
                                 "code": {"coding": [{"system": SYS_ICD10, "code": row[column]}]}})
                diagnoses.append({"condition": {"reference": condition}, "rank": rank,
                                  "use": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/diagnosis-role", "code": role}]}})
        for position, code in enumerate(filter(None, (row.get("FKL24") or "").split(";"))):
            condition = add({"resourceType": "Condition", "id": f"c{key}s{position}",
                             "code": {"coding": [{"system": SYS_ICD10, "code": code}]}})
            diagnoses.append({"condition": {"reference": condition}, "rank": 3 + position,
                              "use": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/diagnosis-role", "code": "CM"}]}})
        encounter: dict[str, Any] = {
            "resourceType": "Encounter", "id": f"e{key}", "status": "finished",
            "identifier": [{"system": SYS_VISIT, "value": row["FKL02"]}],
            "subject": {"reference": patients[participant]}, "serviceProvider": {"reference": organizations[facility_key]},
            "period": {"start": start, **({"end": row["FKL04"]} if row.get("FKL04") else {})},
            "diagnosis": diagnoses,
        }
        if row.get("JENIS_LAYANAN"):
            encounter["serviceType"] = {"coding": [{"system": SYS_SERVICE, "code": row["JENIS_LAYANAN"]}]}
        encounter_ref = add(encounter)
        if row.get("FKL30"):
            add({"resourceType": "Procedure", "id": f"x{key}", "status": "completed", "encounter": {"reference": encounter_ref},
                 "code": {"coding": [{"system": SYS_ICD9CM, "code": row["FKL30"]}]}})
        items = []
        if row.get("FKL19"):
            items.append({"sequence": 1, "encounter": [{"reference": encounter_ref}],
                          "productOrService": {"coding": [{"system": SYS_INACBG, "code": row["FKL19"]}]}})
        for column in TOPUP_COLUMNS:
            if row.get(column):
                items.append({"sequence": len(items) + 1, "encounter": [{"reference": encounter_ref}],
                              "productOrService": {"coding": [{"system": f"{SYS_TOPUP}/{column}", "code": row[column]}]}})
        if not items:
            items.append({"sequence": 1, "encounter": [{"reference": encounter_ref}], "productOrService": {"text": "INA-CBG"}})
        claim: dict[str, Any] = {"resourceType": "Claim", "id": f"k{key}", "status": "active", "use": "claim",
                                 "patient": {"reference": patients[participant]},
                                 "provider": {"reference": organizations[facility_key]},
                                 "extension": [_ext(name, row[column]) for name, column in CLAIM_EXTENSIONS.items() if row.get(column)],
                                 "item": items}
        if row.get("FKL47"):
            claim["total"] = {"value": int(float(row["FKL47"])), "currency": "IDR"}
        add(claim)
        if row.get("CATATAN_KLINIS"):
            add({"resourceType": "Composition", "id": f"r{key}", "status": "final", "title": "Resume medis",
                 "encounter": {"reference": encounter_ref}, "subject": {"reference": patients[participant]},
                 "section": [{"title": "Ringkasan perawatan",
                              "text": {"status": "generated",
                                       "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{html.escape(row['CATATAN_KLINIS'])}</div>"}}]})
        for position, code in enumerate(filter(None, (row.get("BUKTI_TERCATAT") or "").split(";"))):
            if code == "-":
                continue
            add({"resourceType": "DocumentReference", "id": f"d{key}{position}", "status": "current",
                 "type": {"coding": [{"system": SYS_EVIDENCE, "code": code}]},
                 "context": {"encounter": [{"reference": encounter_ref}]}})
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}
