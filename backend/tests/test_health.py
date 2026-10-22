"""Tests for the dataset-independent health endpoint."""

import ast
import asyncio
import os
from pathlib import Path

import httpx

from app import SERVICE_NAME, __version__
from app.main import create_app


def test_health_matches_api_contract_without_data_configuration(
    monkeypatch, tmp_path
):
    """Health stays available without a dataset or BPJS environment setup."""
    for name in tuple(os.environ):
        if name.upper().startswith("BPJS_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    review_db = tmp_path / "private" / "reviews.sqlite3"

    async def request_health():
        transport = httpx.ASGITransport(app=create_app(review_db_path=review_db))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": __version__,
    }
    assert not review_db.exists()


def test_health_application_has_no_dataset_or_analysis_dependencies():
    """The health app imports no data readers or legacy analysis scripts."""
    app_root = Path(__file__).parents[1] / "app"
    forbidden_imports = {
        "pyreadstat",
        "pandas",
        "numpy",
        "subprocess",
        "inspect_metadata",
        "profile_fkrtl",
        "detect_repeat_candidates",
        "detect_cloning_candidates",
        "detect_cloning_v2",
    }

    for source_path in app_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module.split(".")[0])

        assert imported_names.isdisjoint(forbidden_imports), source_path
