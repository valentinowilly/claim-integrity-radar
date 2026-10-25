"""Measure the chunked FKRTL reader on generated synthetic .dta fixtures only."""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import threading
import tempfile
from pathlib import Path
import time
import tracemalloc

import pandas as pd

from scripts.fkrtl_dta_reader import iter_fkrtl_dta
from scripts.fkrtl_dta_provider import LocalFkrtlDtaProvider
from app.services.provider_orchestrator import run_provider_analysis


def _current_rss_bytes() -> int | None:
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("Psapi.dll")
        kernel32 = ctypes.WinDLL("Kernel32.dll")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        get_info = psapi.GetProcessMemoryInfo
        get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        get_info.restype = ctypes.c_int
        ok = get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize) if ok else None
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if os.name == "darwin" else value * 1024)
    except (ImportError, AttributeError):
        return None


class _RssSampler:
    def __init__(self) -> None:
        self.baseline = _current_rss_bytes()
        self.peak = self.baseline
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(0.02):
            current = _current_rss_bytes()
            if current is not None and (self.peak is None or current > self.peak):
                self.peak = current

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        self._thread.join()
        current = _current_rss_bytes()
        if current is not None and (self.peak is None or current > self.peak):
            self.peak = current


def _synthetic_row(index: int) -> dict[str, str]:
    return {
        "PSTV01": f"synthetic-member-{index % 9000:05d}",
        "FKL02": f"synthetic-visit-{index:08d}",
        "FKL03": f"2024-{(index % 12) + 1:02d}-{(index % 27) + 1:02d}",
        "FKL04": f"2024-{(index % 12) + 1:02d}-{((index + 2) % 27) + 1:02d}",
        "FKL05": f"SYN-PROV-{index % 8:02d}",
        "FKL06": f"SYN-CITY-{index % 40:03d}",
        "FKL07": "synthetic-ownership",
        "FKL08": "synthetic-type",
        "FKL09": "synthetic-class",
        "FKL16": f"SYN-AD-{index % 300:03d}",
        "FKL18": f"SYN-DX-{index % 500:03d}",
        "FKL19": f"SYN-GROUP-{index % 20:02d}",
        "FKL30": f"SYN-PROC-{index % 200:03d}",
    }


def benchmark(rows: int, chunk_size: int, mode: str, profile_stages: bool = False) -> dict:
    key = b"benchmark-only-synthetic-key-32-bytes!"
    with tempfile.TemporaryDirectory(prefix="cir_fkrtl_benchmark_") as root:
        root_path = Path(root)
        input_path = root_path / "synthetic-fixture.dta"
        frame = pd.DataFrame.from_records(_synthetic_row(index) for index in range(rows))
        frame.to_stata(input_path, write_index=False)
        del frame
        gc.collect()
        scratch = root_path / "scratch"
        scratch.mkdir()
        summary: dict[str, int] | None = None
        stage_memory: list[dict[str, int | str | None]] = []
        last_traced_current = 0
        overall_traced_peak = 0

        def observe_stage(name: str) -> None:
            nonlocal last_traced_current, overall_traced_peak
            current, interval_peak = tracemalloc.get_traced_memory()
            overall_traced_peak = max(overall_traced_peak, interval_peak)
            stage_memory.append({
                "stage": name,
                "retained_python_allocation_delta_bytes": current - last_traced_current,
                "interval_python_peak_above_previous_stage_bytes": max(0, interval_peak - last_traced_current),
                "sampled_working_set_bytes": _current_rss_bytes(),
            })
            last_traced_current = current
            tracemalloc.reset_peak()

        with _RssSampler() as rss:
            tracemalloc.start()
            tracemalloc.reset_peak()
            started = time.perf_counter()
            if mode == "reader":
                seen = 0
                for chunk, _coverage in iter_fkrtl_dta(
                    input_path,
                    case_reference_secret=key,
                    chunk_size=chunk_size,
                    scratch_directory=scratch,
                ):
                    seen += len(chunk)
                    del chunk
            else:
                result = run_provider_analysis(LocalFkrtlDtaProvider(
                    input_path,
                    case_reference_secret=key,
                    source_classification="synthetic_fixture",
                    chunk_size=chunk_size,
                ), stage_observer=observe_stage if profile_stages else None)
                seen = int(result["data_source"]["adapter_coverage"]["row_count"])
                summary = {
                    "signal_count": int(result["signal_count"]),
                    "unassessable_case_count": int(result["risk_scoring"]["unassessable_case_count"]),
                    "coverage_status_counts": {
                        status: sum(1 for item in result["coverage"] if item.get("status") == status)
                        for status in sorted({item.get("status") for item in result["coverage"]})
                    },
                    "indicator_candidates": {
                        item["code"]: {
                            "candidate_count": item.get("candidate_count"),
                            "eligible_count": item.get("eligible_count"),
                            "unassessed_count": item.get("unassessed_count"),
                            "search_truncated": item.get("search_truncated"),
                            "search_diagnostics": item.get("search_diagnostics", {}),
                        }
                        for item in result["indicators"]
                    },
                    "truncated_indicators": sorted(
                        item["code"] for item in result["indicators"]
                        if item.get("search_truncated") is True
                    ),
                }
                del result
            elapsed = time.perf_counter() - started
            _current, peak = tracemalloc.get_traced_memory()
            overall_traced_peak = max(overall_traced_peak, peak)
            tracemalloc.stop()
        return {
            "fixture_kind": "synthetic_only",
            "mode": mode,
            "rows_requested": rows,
            "rows_read": seen,
            "chunk_size": chunk_size,
            "input_file_bytes": input_path.stat().st_size,
            "processing_elapsed_seconds": round(elapsed, 3),
            "python_traced_peak_bytes": overall_traced_peak,
            "rss_baseline_bytes": rss.baseline,
            "rss_peak_sampled_bytes": rss.peak,
            "rss_delta_sampled_bytes": (
                rss.peak - rss.baseline
                if rss.peak is not None and rss.baseline is not None else None
            ),
            "pipeline_aggregate": summary,
            "stage_memory": stage_memory if profile_stages else None,
            "memory_metric": "tracemalloc peak for Python allocations; excludes some native pandas/NumPy allocations",
            "rss_metric": "sampled process working set every 20ms; may miss short peaks",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=25_000)
    parser.add_argument("--chunk-size", type=int, default=2_000)
    parser.add_argument("--mode", choices=("reader", "pipeline"), default="reader")
    parser.add_argument("--profile-stages", action="store_true", help="sample retained Python allocations at pipeline milestones")
    args = parser.parse_args()
    if args.rows < 1 or args.chunk_size < 1:
        parser.error("--rows and --chunk-size must be positive")
    print(json.dumps(benchmark(args.rows, args.chunk_size, args.mode, args.profile_stages), sort_keys=True))


if __name__ == "__main__":
    main()
