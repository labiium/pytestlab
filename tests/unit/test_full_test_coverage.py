from types import SimpleNamespace

from pytestlab.cli import _semantic_operation_rows
from pytestlab.instruments.operation_contract import OperationDescriptor


def test_semantic_full_test_reports_profile_methods_without_descriptors():
    calls = []

    class Device:
        config = SimpleNamespace(
            operation_options=SimpleNamespace(operations={"read_value": {}, "helper": {}})
        )

        def operation_descriptors(self):
            return (
                OperationDescriptor("read_value", public_method="read_value", safety_class="read"),
            )

        def describe_operation(self, operation_id):
            return {"support": {"supported": True}, "parameters": {}}

        def read_value(self):
            calls.append("read_value")

        def helper(self):
            calls.append("helper")

    rows, failures, warnings, skipped = _semantic_operation_rows(Device(), include_writes=False)

    assert calls == ["read_value"]
    assert failures == 1
    assert warnings == skipped == 0
    assert {(row["alias"], row["status"], row["detail"]) for row in rows} == {
        ("read_value", "ok", "semantic operation passed"),
        ("helper", "fail", "public I/O method has no semantic operation descriptor"),
    }
