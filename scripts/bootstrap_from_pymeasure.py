#!/usr/bin/env python3
"""
bootstrap_from_pymeasure.py
===========================

AST-based extractor that parses PyMeasure instrument drivers and generates
PyTestLab YAML profiles + Python facade stubs.

Usage:
    python bootstrap_from_pymeasure.py /path/to/pymeasure/instruments/keithley/keithley2400.py \
        --out-yaml keithley2400.yaml \
        --out-py keithley2400_facade.py

    # Batch mode — process all PyMeasure drivers
    python bootstrap_from_pymeasure.py /path/to/pymeasure/instruments/ \
        --batch-out-dir ./generated_profiles/
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
#  Data structures for extracted metadata
# ---------------------------------------------------------------------------


@dataclass
class ExtractedProperty:
    """One Instrument.control / measurement / setting entry."""

    name: str
    kind: str  # "control" | "measurement" | "setting"
    get_command: str | None = None
    set_command: str | None = None
    docs: str = ""
    validator: str | None = None
    values: Any = None
    map_values: bool = False
    dynamic: bool = False
    channel_aware: bool = False  # contains {ch} or (@{ch}) placeholder
    cast: str | None = None
    separator: str = ","
    maxsplit: int = -1
    get_process: str | None = None  # AST dump (skipped for now)
    set_process: str | None = None
    preprocess_reply: str | None = None
    check_get_errors: bool = False
    check_set_errors: bool = False


@dataclass
class ExtractedChannel:
    """A Channel subclass or ChannelCreator usage."""

    name: str
    class_name: str | None = None
    properties: list[ExtractedProperty] = field(default_factory=list)
    creator_ids: list[int] = field(default_factory=list)


@dataclass
class ExtractedInstrument:
    """Everything we pulled out of a single PyMeasure driver file."""

    manufacturer: str
    model: str
    device_type: str
    class_name: str
    properties: list[ExtractedProperty] = field(default_factory=list)
    channels: list[ExtractedChannel] = field(default_factory=list)
    custom_methods: list[str] = field(default_factory=list)
    raw_properties: int = 0  # total control/measurement/setting count
    has_custom_logic: bool = False


# ---------------------------------------------------------------------------
#  Validator mapping: PyMeasure → PyTestLab YAML
# ---------------------------------------------------------------------------

VALIDATOR_MAP = {
    "strict_range": "range",
    "strict_discrete_range": "range",  # loses step info
    "truncated_range": "range",  # loses truncation behaviour
    "modular_range": None,  # unsupported — skip or flag
    "modular_range_bidirectional": None,
    "strict_discrete_set": "enum",
    "truncated_discrete_set": "enum",  # loses truncation behaviour
    "joined_validators": None,  # unsupported — flag for manual review
}


# ---------------------------------------------------------------------------
#  AST helpers
# ---------------------------------------------------------------------------


def _literal_value(node: ast.AST) -> Any:
    """Best-effort evaluation of an AST constant / literal."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_literal_value(e) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {_literal_value(k): _literal_value(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Tuple):
        return tuple(_literal_value(e) for e in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal_value(node.operand)
        return -inner if isinstance(inner, (int, float)) else inner
    return None


def _get_attr_name(node: ast.AST) -> str | None:
    """Turn ``Instrument.control`` or ``Channel.control`` into a dotted string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _get_attr_name(node.value)
        if base:
            return f"{base}.{node.attr}"
    return None


def _extract_docstring(node: ast.AST) -> str:
    """Pull the first Constant string out of an Assign RHS."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip()
    return ""


def _has_channel_placeholder(cmd: str | None) -> bool:
    if not cmd:
        return False
    return bool(re.search(r"\{ch\}|\(@\{ch\}\)|\(@\d\)", cmd))


# ---------------------------------------------------------------------------
#  Core extractor — visits AST of one driver file
# ---------------------------------------------------------------------------


class _Extractor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.properties: list[ExtractedProperty] = []
        self.channels: list[ExtractedChannel] = []
        self.custom_methods: list[str] = []
        self.class_name: str = ""
        self._channel_classes: dict[str, list[ExtractedProperty]] = {}

    # ---- public entry ------------------------------------------------------
    def extract(self, source: str, filepath: Path) -> ExtractedInstrument:
        tree = ast.parse(source)
        self.visit(tree)
        return self._build_result(filepath)

    # ---- visitors ----------------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        # Detect Channel subclasses
        bases = [_get_attr_name(b) for b in node.bases]
        if any(b and "Channel" in b for b in bases):
            old_props = self.properties
            self.properties = []
            self.generic_visit(node)
            self._channel_classes[node.name] = self.properties
            self.properties = old_props
            return

        # Detect Instrument subclasses
        if any(b and ("Instrument" in b or "SCPIMixin" in b or "SCPIUnknownMixin" in b) for b in bases):
            self.class_name = node.name
            self.generic_visit(node)
            return

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        if node.name == "__init__":
            return
        # Only count methods inside our target instrument class
        if self.class_name:
            self.custom_methods.append(node.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        if len(node.targets) != 1:
            self.generic_visit(node)
            return
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            self.generic_visit(node)
            return
        prop_name = target.id
        value = node.value
        if isinstance(value, ast.Call):
            call_name = _get_attr_name(value.func)
            if call_name and ("control" in call_name or "measurement" in call_name or "setting" in call_name):
                prop = self._parse_property_call(prop_name, call_name, value)
                if prop:
                    self.properties.append(prop)
        self.generic_visit(node)

    # ---- property parser ---------------------------------------------------
    def _parse_property_call(self, name: str, call_name: str, node: ast.Call) -> ExtractedProperty | None:
        kind = "control"
        if "measurement" in call_name:
            kind = "measurement"
        elif "setting" in call_name:
            kind = "setting"

        args = node.args
        kwargs = {kw.arg: kw.value for kw in node.keywords}

        get_cmd = _literal_value(args[0]) if len(args) > 0 else None
        set_cmd = _literal_value(args[1]) if len(args) > 1 else None
        docs = _literal_value(args[2]) if len(args) > 2 else ""

        if not isinstance(get_cmd, str):
            return None

        validator_node = kwargs.get("validator")
        validator_name = None
        if isinstance(validator_node, ast.Name):
            validator_name = validator_node.id
        elif isinstance(validator_node, ast.Attribute):
            validator_name = validator_node.attr

        values = _literal_value(kwargs.get("values"))
        map_values = _literal_value(kwargs.get("map_values"))
        dynamic = _literal_value(kwargs.get("dynamic"))
        cast = _literal_value(kwargs.get("cast"))
        separator = _literal_value(kwargs.get("separator"))
        maxsplit = _literal_value(kwargs.get("maxsplit"))
        check_get = bool(kwargs.get("check_get_errors"))
        check_set = bool(kwargs.get("check_set_errors"))

        return ExtractedProperty(
            name=name,
            kind=kind,
            get_command=get_cmd,
            set_command=set_cmd if isinstance(set_cmd, str) else None,
            docs=docs if isinstance(docs, str) else "",
            validator=validator_name,
            values=values,
            map_values=bool(map_values),
            dynamic=bool(dynamic),
            channel_aware=_has_channel_placeholder(get_cmd) or _has_channel_placeholder(set_cmd),
            cast=cast if isinstance(cast, str) else None,
            separator=separator if isinstance(separator, str) else ",",
            maxsplit=maxsplit if isinstance(maxsplit, int) else -1,
            check_get_errors=check_get,
            check_set_errors=check_set,
        )

    # ---- result assembly ---------------------------------------------------
    def _build_result(self, filepath: Path) -> ExtractedInstrument:
        manufacturer = filepath.parent.name.replace("_", " ").title()
        model = filepath.stem
        device_type = self._infer_device_type(model)

        # Merge channel class properties into the instrument if we detected creators
        # (simplified: we just keep channels separate for now)
        channels = [
            ExtractedChannel(name=cls_name, properties=props)
            for cls_name, props in self._channel_classes.items()
        ]

        return ExtractedInstrument(
            manufacturer=manufacturer,
            model=model,
            device_type=device_type,
            class_name=self.class_name,
            properties=self.properties,
            channels=channels,
            custom_methods=self.custom_methods,
            raw_properties=len(self.properties),
            has_custom_logic=len(self.custom_methods) > 0,
        )

    @staticmethod
    def _infer_device_type(model: str) -> str:
        """Naïve heuristic from model name / filename."""
        m = model.lower()
        if any(x in m for x in ("scope", "dso", "mso", "oscillo")):
            return "oscilloscope"
        if any(x in m for x in ("psu", "supply", "e36", "n67", "bop")):
            return "power_supply"
        if any(x in m for x in ("dmm", "multimeter", "344", "2000")):
            return "multimeter"
        if any(x in m for x in ("awg", "arb", "funcgen", "332", "335", "811")):
            return "waveform_generator"
        if any(x in m for x in ("vna", "network", "8722", "5062")):
            return "vector_network_analyzer"
        if any(x in m for x in ("source", "smu", "2400", "2450", "2600")):
            return "source_meter"
        if any(x in m for x in ("spectrum", "sa", "e4408", "fsl")):
            return "spectrum_analyzer"
        if any(x in m for x in ("load", "el34")):
            return "dc_active_load"
        return "generic_instrument"


# ---------------------------------------------------------------------------
#  YAML generator
# ---------------------------------------------------------------------------


def _to_yaml_command_name(prop_name: str, kind: str) -> str:
    """Convert property name to a clean YAML key."""
    if kind == "measurement":
        return f"get_{prop_name}"
    if kind == "setting":
        return f"set_{prop_name}"
    return f"set_{prop_name}"


def _to_yaml_query_name(prop_name: str) -> str:
    return f"get_{prop_name}"


def _build_yaml(extracted: ExtractedInstrument) -> dict[str, Any]:
    """Turn extracted metadata into a PyTestLab-compatible YAML dict."""
    commands: dict[str, Any] = {}
    queries: dict[str, Any] = {}

    for prop in extracted.properties:
        if prop.kind in ("control", "setting") and prop.set_command:
            yaml_cmd: dict[str, Any] = {"template": prop.set_command}
            if prop.channel_aware:
                yaml_cmd["defaults"] = {"channel": 1}
            if prop.values and isinstance(prop.values, dict) and prop.map_values:
                yaml_cmd["enums"] = {
                    "value" if len(prop.values) == 2 and all(isinstance(v, bool) for v in prop.values) else "state":
                    {str(k).lower(): v for k, v in prop.values.items()}
                }
            if prop.values and isinstance(prop.values, list) and len(prop.values) == 2:
                yaml_cmd["validators"] = {"value": {"min": prop.values[0], "max": prop.values[1]}}
            commands[_to_yaml_command_name(prop.name, prop.kind)] = yaml_cmd

        if prop.kind in ("control", "measurement") and prop.get_command:
            yaml_qry: dict[str, Any] = {"template": prop.get_command}
            if prop.channel_aware:
                yaml_qry["defaults"] = {"channel": 1}
            resp_type = "str"
            if prop.cast:
                resp_type = prop.cast
            elif prop.values and isinstance(prop.values, list) and len(prop.values) == 2:
                resp_type = "float"
            yaml_qry["response"] = {"type": resp_type}
            queries[_to_yaml_query_name(prop.name)] = yaml_qry

    profile: dict[str, Any] = {
        "manufacturer": extracted.manufacturer,
        "model": extracted.model,
        "device_type": extracted.device_type,
        "role": "measurement",
    }

    if extracted.channels:
        profile["channels"] = [
            {"channel_id": i + 1, "description": ch.name}
            for i, ch in enumerate(extracted.channels)
        ]

    profile["scpi"] = {
        "commands": commands,
        "queries": queries,
    }

    return profile


def generate_yaml(extracted: ExtractedInstrument, out_path: Path | None = None) -> str:
    yaml_dict = _build_yaml(extracted)
    text = yaml.dump(yaml_dict, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text)
    return text


# ---------------------------------------------------------------------------
#  Python facade stub generator
# ---------------------------------------------------------------------------


def _to_method_name(prop_name: str, kind: str) -> str:
    """CamelCase or snake_case method name from property."""
    if kind == "measurement":
        return prop_name  # keep as-is for getters
    if prop_name.startswith("set_") or prop_name.startswith("get_"):
        return prop_name
    return f"set_{prop_name}"


def _to_getter_name(prop_name: str) -> str:
    if prop_name.startswith("get_"):
        return prop_name
    return f"get_{prop_name}"


def _build_py_imports(extracted: ExtractedInstrument) -> str:
    return f"""from pytestlab.instruments.instrument import Instrument
from pytestlab.config.instrument_config import InstrumentConfig


class {extracted.class_name or 'AutoGeneratedInstrument'}(Instrument):
    \"\"\"Auto-generated facade for {extracted.manufacturer} {extracted.model}.\"\"\"
"""


def _build_py_method(prop: ExtractedProperty) -> str | None:
    """Generate a single facade method for a property."""
    lines: list[str] = []
    arg_type = "str"
    if prop.values and isinstance(prop.values, list) and len(prop.values) == 2:
        arg_type = "float"
    elif prop.values and isinstance(prop.values, dict):
        if all(isinstance(v, bool) for v in prop.values.values()):
            arg_type = "bool"
        elif all(isinstance(v, (int, float)) for v in prop.values.values()):
            arg_type = "str"

    if prop.kind in ("control", "setting") and prop.set_command:
        method = _to_method_name(prop.name, "control")
        args = [f"value: {arg_type}"]
        if prop.channel_aware:
            args.insert(0, "channel: int = 1")
        lines.append(f"    def {method}(self, {', '.join(args)}) -> None:")
        lines.append(f'        """{prop.docs or f"Set {prop.name}"}"""')
        call = f'self.scpi_engine.build("set_{prop.name}", value=value)[0]'
        if prop.channel_aware:
            call = f'self.scpi_engine.build("set_{prop.name}", channel=channel, value=value)[0]'
        lines.append(f"        cmd = {call}")
        lines.append("        self._send_command(cmd)")
        lines.append("")

    if prop.kind in ("control", "measurement") and prop.get_command:
        method = _to_getter_name(prop.name)
        args = []
        if prop.channel_aware:
            args = ["channel: int = 1"]
        lines.append(f"    def {method}(self{', ' + ', '.join(args) if args else ''}) -> {arg_type}:")
        lines.append(f'        """{prop.docs or f"Get {prop.name}"}"""')
        call = f'self.scpi_engine.build("get_{prop.name}")[0]'
        if prop.channel_aware:
            call = f'self.scpi_engine.build("get_{prop.name}", channel=channel)[0]'
        lines.append(f"        q = {call}")
        lines.append("        resp = self._query(q)")
        lines.append(f"        return self.scpi_engine.parse(\"get_{prop.name}\", resp)")
        lines.append("")

    return "\n".join(lines) if lines else None


def generate_python_stub(extracted: ExtractedInstrument, out_path: Path | None = None) -> str:
    parts = [_build_py_imports(extracted)]
    for prop in extracted.properties:
        method_src = _build_py_method(prop)
        if method_src:
            parts.append(method_src)
    text = "\n".join(parts)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text)
    return text


# ---------------------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bootstrap PyTestLab profiles from PyMeasure drivers")
    p.add_argument("source", type=Path, help="Path to a single .py file or a directory of drivers")
    p.add_argument("--out-yaml", type=Path, default=None, help="Output YAML file path")
    p.add_argument("--out-py", type=Path, default=None, help="Output Python stub path")
    p.add_argument("--batch-out-dir", type=Path, default=None, help="Batch output directory")
    p.add_argument("--json-summary", type=Path, default=None, help="Write JSON summary of extraction")
    return p.parse_args()


def _process_single(source_file: Path, out_yaml: Path | None, out_py: Path | None) -> None:
    source = source_file.read_text()
    extractor = _Extractor()
    extracted = extractor.extract(source, source_file)

    print(f"Class: {extracted.class_name}")
    print(f"Properties: {extracted.raw_properties}")
    print(f"Custom methods: {len(extracted.custom_methods)}")
    print(f"Channels: {len(extracted.channels)}")

    if out_yaml:
        generate_yaml(extracted, out_yaml)
        print(f"Wrote YAML → {out_yaml}")

    if out_py:
        generate_python_stub(extracted, out_py)
        print(f"Wrote Python stub → {out_py}")


def _batch_process(source_dir: Path, out_dir: Path, json_summary: Path | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict[str, Any]] = []

    py_files = sorted(source_dir.rglob("*.py"))
    # Exclude base infrastructure files
    exclude = {"__init__.py", "channel.py", "common_base.py", "validators.py",
               "resources.py", "generic_types.py", "fakes.py", "comedi.py", "instrument.py"}
    py_files = [f for f in py_files if f.name not in exclude]

    processed = 0
    for src in py_files:
        try:
            source = src.read_text()
            extractor = _Extractor()
            extracted = extractor.extract(source, src)
            if extracted.raw_properties == 0:
                continue  # skip files with no extractable properties

            rel = src.relative_to(source_dir)
            yaml_path = out_dir / rel.with_suffix(".yaml")
            py_path = out_dir / rel.with_suffix(".py")

            generate_yaml(extracted, yaml_path)
            generate_python_stub(extracted, py_path)

            all_results.append({
                "file": str(rel),
                "class": extracted.class_name,
                "manufacturer": extracted.manufacturer,
                "model": extracted.model,
                "device_type": extracted.device_type,
                "properties": extracted.raw_properties,
                "custom_methods": len(extracted.custom_methods),
                "channels": len(extracted.channels),
                "has_custom_logic": extracted.has_custom_logic,
            })
            processed += 1
            print(f"  ✓ {rel} ({extracted.raw_properties} properties)")
        except SyntaxError as e:
            print(f"  ✗ {rel} — SyntaxError: {e}")
        except Exception as e:
            print(f"  ✗ {rel} — {type(e).__name__}: {e}")

    print(f"\nProcessed {processed}/{len(py_files)} drivers.")
    print(f"Output written to: {out_dir}")

    if json_summary:
        json_summary.write_text(json.dumps(all_results, indent=2))
        print(f"Summary written to: {json_summary}")


def main() -> None:
    args = _parse_args()
    if args.source.is_file():
        _process_single(args.source, args.out_yaml, args.out_py)
    elif args.source.is_dir():
        if not args.batch_out_dir:
            print("ERROR: --batch-out-dir is required when source is a directory.", file=sys.stderr)
            sys.exit(1)
        _batch_process(args.source, args.batch_out_dir, args.json_summary)
    else:
        print(f"ERROR: Source path does not exist: {args.source}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
