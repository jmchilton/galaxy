#!/usr/bin/env python3
"""Benchmark representative external set_metadata runs on Python 3.15.

Run from the Galaxy repository root with a Python 3.15 environment::

    PYTHONPATH=lib python scripts/benchmark_set_metadata.py
"""

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPOSITORY_ROOT / "lib"), str(REPOSITORY_ROOT / "test")]

from unit.app.tools.test_metadata import TestMetadata  # noqa: E402

from galaxy.job_execution.metadata_constants import LAZY_IMPORTS_ENV  # noqa: E402
from galaxy.util import galaxy_directory  # noqa: E402

CASES = {
    "fasta-small": ("fasta", ">seq1\nGCTGCATG\n", {"data_lines": 2, "sequences": 1}, (), None),
    "fasta-sniff": ("data", ">seq1\nGCTGCATG\n", {"data_lines": 2, "sequences": 1}, (), "fasta"),
    "tabular-1k": ("tabular", "".join(f"{i}\t{i + 1}\t{i + 2}\n" for i in range(1_000)), {}, (), None),
    "bam-small": ("bam", REPOSITORY_ROOT / "test-data/1.bam", {}, ("bam_index",), None),
}


def prepare_case(case_name, strategy):
    extension, contents, expected_metadata, expected_metadata_files, expected_sniffed_extension = CASES[case_name]
    case = TestMetadata()
    case.setUp()
    case.app.config.metadata_strategy = strategy
    source_file_name = os.path.join(galaxy_directory(), "test/functional/tools/for_workflows/cat.xml")
    case._init_tool_for_path(source_file_name)
    output_dataset = case._create_output_dataset(extension=extension)
    sa_session = case.app.model.session
    sa_session.commit()
    output_datasets = {"out_file1": output_dataset}
    command = case.metadata_command(output_datasets)
    if expected_sniffed_extension:
        case._write_galaxy_json(f'{{"type": "dataset", "dataset_id": "{output_dataset.dataset.id}", "ext": "_sniff_"}}')
    if isinstance(contents, Path):
        Path(output_dataset.dataset.get_file_name()).write_bytes(contents.read_bytes())
    else:
        case._write_output_dataset_contents(output_dataset, contents)
    case._write_job_files()
    return (
        case,
        output_dataset,
        sa_session,
        command,
        expected_metadata,
        expected_metadata_files,
        expected_sniffed_extension,
    )


def run_once(case, command, mode):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "lib")
    environment[LAZY_IMPORTS_ENV] = mode
    environment["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{environment['PATH']}"
    started = time.perf_counter()
    process = subprocess.run(
        command,
        shell=True,
        cwd=case.job_working_directory,
        env=environment,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started
    if process.returncode:
        raise RuntimeError(
            f"set_metadata failed in {mode!r} mode with exit code {process.returncode}:\n{process.stderr}"
        )
    return elapsed


def validate_result(
    case,
    output_dataset,
    sa_session,
    expected_metadata,
    expected_metadata_files,
    expected_sniffed_extension,
):
    strategy = case.metadata_compute_strategy
    assert strategy
    if not strategy.external_metadata_set_successfully(
        output_dataset, "out_file1", sa_session, working_directory=case.job_working_directory
    ):
        raise RuntimeError("set_metadata did not produce a successful metadata result")
    if expected_metadata_files or expected_sniffed_extension:
        export_directory = Path(case.job_working_directory) / "metadata" / "outputs_populated"
        dataset_attributes = next(
            attributes
            for attributes in json.loads((export_directory / "datasets_attrs.txt").read_text())
            if attributes.get("id") == output_dataset.id
        )
        if expected_sniffed_extension:
            actual_extension = dataset_attributes["extension"]
            if actual_extension != expected_sniffed_extension:
                raise RuntimeError(
                    f"sniffed extension: expected {expected_sniffed_extension!r}, got {actual_extension!r}"
                )
            output_dataset.extension = actual_extension
        for name in expected_metadata_files:
            serialized_file = dataset_attributes["metadata"].get(name)
            if not isinstance(serialized_file, dict) or serialized_file.get("model_class") != "MetadataFile":
                raise RuntimeError(f"metadata {name!r} was not serialized as a MetadataFile")
            if file_name := serialized_file.get("file_name"):
                if not (export_directory / file_name).is_file():
                    raise RuntimeError(f"staged metadata file {file_name!r} does not exist")
        if expected_metadata_files:
            return
    strategy.load_metadata(output_dataset, "out_file1", sa_session, working_directory=case.job_working_directory)
    for name, expected_value in expected_metadata.items():
        actual_value = getattr(output_dataset.metadata, name)
        if actual_value != expected_value:
            raise RuntimeError(f"metadata {name!r}: expected {expected_value!r}, got {actual_value!r}")


def benchmark_case(case_name, strategy, warmups, repetitions):
    (
        case,
        output_dataset,
        sa_session,
        command,
        expected_metadata,
        expected_metadata_files,
        expected_sniffed_extension,
    ) = prepare_case(case_name, strategy)
    timings = {"normal": [], "all": []}
    try:
        for _ in range(warmups):
            for mode in ("normal", "all"):
                run_once(case, command, mode)
                validate_result(
                    case,
                    output_dataset,
                    sa_session,
                    expected_metadata,
                    expected_metadata_files,
                    expected_sniffed_extension,
                )
        for repetition in range(repetitions):
            # Reverse the order on alternate repetitions to reduce cache/order bias.
            modes = ("normal", "all") if repetition % 2 == 0 else ("all", "normal")
            for mode in modes:
                timings[mode].append(run_once(case, command, mode))
                validate_result(
                    case,
                    output_dataset,
                    sa_session,
                    expected_metadata,
                    expected_metadata_files,
                    expected_sniffed_extension,
                )
    finally:
        case.tearDown()
        case.tear_down_app()
    return timings


def summarize(timings):
    normal_median = statistics.median(timings["normal"])
    lazy_median = statistics.median(timings["all"])
    return {
        mode: {
            "median_seconds": statistics.median(values),
            "mean_seconds": statistics.mean(values),
            "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
            "mean_standard_error_seconds": (
                statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
            ),
            "min_seconds": min(values),
            "samples_seconds": values,
        }
        for mode, values in timings.items()
    } | {
        "speedup": normal_median / lazy_median,
        "time_reduction_percent": (normal_median - lazy_median) / normal_median * 100,
    }


def print_summary(results):
    print("case                   normal median  normal mean SE  lazy median  lazy mean SE  speedup  reduction")
    for case_name, result in results.items():
        normal_standard_error = result["normal"]["mean_standard_error_seconds"]
        lazy_standard_error = result["all"]["mean_standard_error_seconds"]
        normal_standard_error_display = f"{normal_standard_error:.3f}s" if normal_standard_error is not None else "n/a"
        lazy_standard_error_display = f"{lazy_standard_error:.3f}s" if lazy_standard_error is not None else "n/a"
        print(
            f"{case_name:<22} {result['normal']['median_seconds']:>10.3f}s"
            f" {normal_standard_error_display:>15}"
            f" {result['all']['median_seconds']:>11.3f}s"
            f" {lazy_standard_error_display:>12}"
            f" {result['speedup']:>7.2f}x {result['time_reduction_percent']:>8.1f}%"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=CASES, dest="cases")
    parser.add_argument(
        "--strategy",
        action="append",
        choices=("directory", "extended"),
        dest="strategies",
        help="metadata strategy to benchmark; defaults to directory",
    )
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--json", type=Path, dest="json_path")
    args = parser.parse_args()
    if not hasattr(sys, "set_lazy_imports"):
        parser.error("this benchmark requires Python 3.15 with sys.set_lazy_imports")
    if args.warmups < 0 or args.repetitions < 1:
        parser.error("--warmups must be non-negative and --repetitions must be positive")

    metadata = {
        "python": sys.version,
        "platform": platform.platform(),
        "warmups": args.warmups,
        "repetitions": args.repetitions,
    }
    results = {}
    for strategy in args.strategies or ("directory",):
        for case_name in args.cases or CASES:
            result_name = f"{strategy}/{case_name}"
            results[result_name] = summarize(benchmark_case(case_name, strategy, args.warmups, args.repetitions))
    print_summary(results)
    if args.json_path:
        args.json_path.write_text(json.dumps({"metadata": metadata, "results": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
