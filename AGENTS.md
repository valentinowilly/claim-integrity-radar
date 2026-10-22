# Claim Integrity Radar — Project Instructions

## Product

Build a professional, enterprise-style web application for Claim Integrity Radar, an audit decision-support prototype for Healthkathon BPJS Kesehatan 2026.

## Architecture

- Frontend: React, TypeScript, Vite, Tailwind CSS, and Recharts.
- Backend: Python and FastAPI.
- Analytics: pandas and NumPy; use scikit-learn only when justified and testable.
- Keep frontend, backend, API schemas, data processing, and risk detectors in separate modules.

## Data protection

- Use synthetic data by default for development, screenshots, and public demos.
- The actual BPJS .dta files are stored outside this repository.
- Never upload, copy, print, index, or commit raw BPJS data.
- Do not execute existing scripts that access the real dataset unless explicitly instructed.
- For real-data profiling, output aggregate statistics only; never expose individual rows or identifiers.
- Keep real data processing local and consistent with the authorized data-use terms.

## Analytical integrity

- Risk indicators are not proof of fraud.
- Do not invent evaluation metrics or claim that a feature works before testing it.
- FKL48 represents post-verification cost; do not use it as a pre-verification predictor.
- The currently inspected FKRTL schema does not establish a unique hospital identifier. Do not invent hospital-level rankings.
- Clearly distinguish synthetic-demo findings from actual sample-data findings.
- Keep human review in the decision workflow.

## Development workflow

- Inspect the existing repository before changing files.
- Preserve the existing profiling and detection scripts unless a change is justified.
- Work incrementally and explain the purpose of each major change.
- Define and maintain API contracts between frontend and backend.
- Run relevant tests and builds after changes; report actual results and errors.
- Do not replace real API integration with hardcoded dashboard metrics.
- Before large refactors, present the plan and wait for approval.
