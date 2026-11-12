"""Claim intake from several sources: E-Klaim CSV, RME/SATUSEHAT FHIR JSON, and facility PDF documents.

Every source is turned into the same canonical claim row (the BPJS column format), so one validated import
path and one analysis serve them all. Documents keep their pages, extracted facts and page citations, so a
verifier can always open the page a value came from.
"""
