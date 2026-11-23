import ast
import importlib
import inspect
import re
import textwrap
from pathlib import Path

import pytest

PUBLIC_PACKAGES = (
    "pytestlab",
    "pytestlab.common",
    "pytestlab.compliance",
    "pytestlab.config",
    "pytestlab.devices",
    "pytestlab.experiments",
    "pytestlab.instruments",
    "pytestlab.measurements",
    "pytestlab.plotting",
    "pytestlab.sim.circuit",
    "pytestlab.sim.circuit.calibration",
    "pytestlab.sim.circuit.injectors",
    "pytestlab.sim.circuit.instruments",
    "pytestlab.sim.circuit.noise",
    "pytestlab.sim.circuit.simulators",
    "pytestlab.twin",
    "pytestlab.uncertainty",
)


def _source_docstring(value: type) -> str | None:
    source = textwrap.dedent(inspect.getsource(value))
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    return ast.get_docstring(node, clean=True)


@pytest.mark.parametrize("package_name", PUBLIC_PACKAGES)
def test_exported_classes_have_their_own_docstrings(package_name: str) -> None:
    package = importlib.import_module(package_name)
    missing = []
    for name in package.__all__:
        value = getattr(package, name)
        if inspect.isclass(value) and not _source_docstring(value):
            missing.append(name)

    assert missing == [], f"{package_name} exports undocumented classes: {missing}"


def test_gui_package_import_is_lazy_without_widget_dependencies() -> None:
    gui = importlib.import_module("pytestlab.gui")

    assert "run_coro_safely" not in gui.__all__
    assert "InstrumentPanel" in gui.__all__

    tree = ast.parse(Path("pytestlab/gui/builder.py").read_text(encoding="utf-8"))
    class_docs = {
        node.name: ast.get_docstring(node, clean=True)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    for name in {"InstrumentPanel", "Slider", "Toggle", "Button"}:
        assert class_docs[name], f"pytestlab.gui.{name} has no class docstring"


def test_every_exported_class_is_in_the_api_reference() -> None:
    api_text = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("docs/en/api").rglob("*.md")
    )
    directives = set(re.findall(r"^:::\s+([\w.]+)", api_text, flags=re.MULTILINE))
    classes: dict[type, set[str]] = {}
    for package_name in PUBLIC_PACKAGES:
        package = importlib.import_module(package_name)
        for name in package.__all__:
            value = getattr(package, name)
            if inspect.isclass(value):
                classes.setdefault(value, set()).add(f"{package_name}.{name}")

    missing = []
    for value, export_paths in classes.items():
        class_path = f"{value.__module__}.{value.__qualname__}"
        module_path = value.__module__
        if not ({class_path, module_path, *export_paths} & directives):
            missing.append(class_path)

    assert missing == [], f"Exported classes absent from docs/en/api: {sorted(missing)}"
