from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT_PREFIX = "__PTL_BENCH__"


@dataclass(frozen=True)
class BenchmarkSpec:
    name: str
    command: list[str]


@dataclass(frozen=True)
class Sample:
    seconds: float
    rss_kb: int


BENCHMARKS = [
    BenchmarkSpec("python_noop", ["uv", "run", "--", "python", "-c", "pass"]),
    BenchmarkSpec("import_pytestlab", ["uv", "run", "--", "python", "-c", "import pytestlab"]),
    BenchmarkSpec(
        "import_pytestlab_cli",
        ["uv", "run", "--", "python", "-c", "import pytestlab.cli"],
    ),
    BenchmarkSpec(
        "import_autoinstrument",
        [
            "uv",
            "run",
            "--",
            "python",
            "-c",
            "from pytestlab.instruments.AutoInstrument import AutoInstrument",
        ],
    ),
    BenchmarkSpec("cli_help", ["uv", "run", "pytestlab", "--help"]),
    BenchmarkSpec("cli_version", ["uv", "run", "pytestlab", "--version"]),
    BenchmarkSpec("profile_list", ["uv", "run", "pytestlab", "profile", "list"]),
    BenchmarkSpec(
        "profile_show",
        ["uv", "run", "pytestlab", "profile", "show", "keysight/EDU34450A"],
    ),
    BenchmarkSpec(
        "profile_schema",
        ["uv", "run", "pytestlab", "profile", "schema", "oscilloscope"],
    ),
    BenchmarkSpec(
        "bench_validate",
        ["uv", "run", "pytestlab", "bench", "validate", "examples/bench.yaml"],
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark pytestlab CLI startup and import paths.")
    parser.add_argument("--repeats", type=int, default=5, help="Number of measured runs per command.")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "benchmarks" / "cli_benchmark_results.json",
        help="Path to write machine-readable benchmark results.",
    )
    return parser.parse_args()


def run_timed(command: list[str]) -> Sample:
    timed_command = ["/usr/bin/time", "-f", f"{RESULT_PREFIX} %e %M", *command]
    completed = subprocess.run(
        timed_command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )

    lines = [line for line in completed.stderr.splitlines() if line.startswith(RESULT_PREFIX)]
    if not lines:
        raise RuntimeError(f"Timing marker missing for command: {' '.join(command)}")

    _, seconds, rss_kb = lines[-1].split()
    return Sample(seconds=float(seconds), rss_kb=int(rss_kb))


def summarize(spec: BenchmarkSpec, samples: list[Sample]) -> dict[str, object]:
    seconds = [sample.seconds for sample in samples]
    rss_values = [sample.rss_kb for sample in samples]
    return {
        "name": spec.name,
        "command": spec.command,
        "samples": [asdict(sample) for sample in samples],
        "mean_seconds": round(statistics.mean(seconds), 4),
        "min_seconds": round(min(seconds), 4),
        "max_seconds": round(max(seconds), 4),
        "mean_rss_kb": round(statistics.mean(rss_values), 2),
        "max_rss_kb": max(rss_values),
    }


def print_summary(results: list[dict[str, object]]) -> None:
    print(f"{'benchmark':<22} {'mean(s)':>8} {'min':>8} {'max':>8} {'rss_kb':>10}")
    print("-" * 62)
    for result in results:
        print(
            f"{result['name']:<22} "
            f"{result['mean_seconds']:>8.4f} "
            f"{result['min_seconds']:>8.4f} "
            f"{result['max_seconds']:>8.4f} "
            f"{int(float(result['mean_rss_kb'])):>10}"
        )


def main() -> int:
    args = parse_args()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    for spec in BENCHMARKS:
        samples = [run_timed(spec.command) for _ in range(args.repeats)]
        results.append(summarize(spec, samples))

    payload = {
        "root": str(ROOT),
        "repeats": args.repeats,
        "results": results,
    }
    args.json_out.write_text(json.dumps(payload, indent=2) + "\n")

    print_summary(results)
    print(f"\nWrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
