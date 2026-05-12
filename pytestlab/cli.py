from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

TOP_LEVEL_HELP = """Usage: {program} [OPTIONS] COMMAND [ARGS]...

PyTestLab: Scientific test & measurement toolbox CLI.

Options:
  --version   Show version and exit.
  --help      Show this message and exit.

Commands:
  run
  list
  replay
  profile
  instrument
  bench
  sim-profile
"""


def _get_version() -> str:
    from importlib import metadata

    try:
        from pytestlab import __version__ as source_version

        return source_version
    except Exception:
        pass

    try:
        return metadata.version("pytestlab")
    except Exception:
        return "unknown"


def _package_root():
    from pathlib import Path

    return Path(__file__).resolve().parent


def _profiles_root():
    return _package_root() / "profiles"


def _program_name() -> str:
    return Path(sys.argv[0]).name or "ptl"


def _print_top_level_help() -> int:
    print(TOP_LEVEL_HELP.format(program=_program_name()))
    return 0


def _print_version() -> int:
    print(f"PyTestLab version {_get_version()}")
    return 0


def _profile_list() -> int:
    print("Available Profiles")
    profiles_root = _profiles_root()
    for vendor_dir in sorted(path for path in profiles_root.iterdir() if path.is_dir()):
        for profile_file in sorted(vendor_dir.glob("*.yaml")):
            rel = profile_file.relative_to(profiles_root).with_suffix("")
            print(rel.as_posix())
    return 0


def _profile_show(profile_key_or_path: str) -> int:
    from pathlib import Path

    from pytestlab.config.loader import resolve_profile_key_to_path

    profile_path = Path(profile_key_or_path)
    if not profile_path.is_file():
        profile_path = resolve_profile_key_to_path(profile_key_or_path)
    print(f"Profile: {profile_key_or_path}")
    print(profile_path.read_text().rstrip())
    return 0


def _profile_schema(instrument_type: str) -> int:
    from pytestlab.config.schema_validator import SchemaValidator

    schema = SchemaValidator().get_instrument_schema(instrument_type, format_output=True)
    print(f"Schema for {instrument_type}:")
    print(schema)
    return 0


def _list_profiles() -> int:
    print("Available instrument profiles:")
    return _profile_list()


def _bench_validate(bench_yaml_path: str) -> int:
    from pathlib import Path

    import yaml

    from pytestlab.config.bench_config import BenchConfigExtended
    from pytestlab.config.loader import load_profile

    bench_path = Path(bench_yaml_path)
    with bench_path.open() as handle:
        data = yaml.safe_load(handle)

    config = BenchConfigExtended.model_validate(data)
    print(f"Bench configuration '{bench_yaml_path}' is valid.")
    print("Validating individual instrument profiles...")
    for alias, entry in config.instruments.items():
        load_profile(entry.profile)
        print(f"  OK Profile '{entry.profile}' for alias '{alias}' loaded successfully.")
    return 0


def _fallback_main() -> int:
    from pytestlab import cli_typer

    return int(cli_typer.main() or 0)


def __getattr__(name: str) -> Any:
    from pytestlab import cli_typer

    value = getattr(cli_typer, name)
    globals()[name] = value
    return value


def _is_option_like(value: str) -> bool:
    return value.startswith("-")


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv == ["--help"] or argv == ["-h"]:
        return _print_top_level_help()
    if argv == ["--version"]:
        return _print_version()

    if argv == ["profile", "list"]:
        return _profile_list()
    if len(argv) == 3 and argv[:2] == ["profile", "show"] and not _is_option_like(argv[2]):
        return _profile_show(argv[2])
    if len(argv) == 3 and argv[:2] == ["profile", "schema"] and not _is_option_like(argv[2]):
        return _profile_schema(argv[2])
    if argv == ["list", "profiles"]:
        return _list_profiles()
    if len(argv) == 3 and argv[:2] == ["bench", "validate"] and not _is_option_like(argv[2]):
        return _bench_validate(argv[2])

    return _fallback_main()


if __name__ == "__main__":
    raise SystemExit(main())
