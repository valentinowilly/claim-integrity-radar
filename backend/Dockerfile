# Claim Integrity Radar API (FastAPI). The image carries the OCR models, so it reads documents without internet.
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DEFAULT_TIMEOUT=180 PIP_RETRIES=10
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# Fetch the OCR model files at build time (they are stored inside the package folder).
RUN python -c "from rapidocr import RapidOCR; RapidOCR()"

COPY app app
COPY scripts scripts
RUN useradd --create-home --uid 10001 cir && mkdir -p /data/documents /data/kiriman && chown -R cir /data
USER cir

EXPOSE 8000
# The schema is created or upgraded by the versioned migrations (additive only), then the API starts.
CMD ["sh", "-c", "python -m scripts.db_migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${CIR_API_WORKERS:-1}"]
