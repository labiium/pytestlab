from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "benchmarks" / "cli_smoke_results.json"


@dataclass(frozen=True)
class SmokeSpec:
    name: str
    command: list[str]
    expected: str


SPECS = [
    SmokeSpec("help", ["uv", "run", "ptl", "--help"], "PyTestLab"),
    SmokeSpec("version", ["uv", "run", "ptl", "--version"], "PyTestLab version"),
    SmokeSpec("profile_list", ["uv", "run", "ptl", "profile", "list"], "Available Profiles"),
    SmokeSpec(
        "profile_show",
        ["uv", "run", "ptl", "profile", "show", "keysight/EDU34450A"],
        "Profile: keysight/EDU34450A",
    ),
    SmokeSpec(
        "bench_validate",
        ["uv", "run", "ptl", "bench", "validate", "examples/bench.yaml"],
        "is valid",
    ),
]


def main() -> int:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    failures: list[str] = []

    for spec in SPECS:
        completed = subprocess.run(
            spec.command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        success = completed.returncode == 0 and spec.expected in completed.stdout
        results.append(
            {
                "name": spec.name,
                "command": spec.command,
                "returncode": completed.returncode,
                "expected": spec.expected,
                "success": success,
            }
        )
        if not success:
            failures.append(
                f"{spec.name}: rc={completed.returncode}, expected={spec.expected!r}, "
                f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
            )

    RESULT_PATH.write_text(json.dumps({"root": str(ROOT), "results": results}, indent=2) + "\n")

    if failures:
        raise SystemExit("\n".join(failures))

    print(f"Smoke checks passed for {len(results)} commands.")
    print(f"Wrote {RESULT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
