from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pytestlab.cli import app
from pytestlab.errors import ReplayMismatchError
from pytestlab.instruments.backends.replay_backend import ReplayBackend
from pytestlab.validation.hardware_parity import HardwareParityError
from pytestlab.validation.hardware_parity import build_replay_fixture
from pytestlab.validation.hardware_parity import compare_replay_to_expected
from pytestlab.validation.hardware_parity import decode_keysight_byte_waveform
from pytestlab.validation.hardware_parity import load_replay_fixture
from pytestlab.validation.hardware_parity import write_replay_fixture


def _binblock(payload: bytes) -> bytes:
    length = str(len(payload)).encode("ascii")
    return b"#" + str(len(length)).encode("ascii") + length + payload


def _fixture():
    raw_payload = bytes([120, 124, 128, 132, 136, 132, 128, 124])
    preamble = "0,0,8,1,1e-6,0,0,0.01,-1.28,0"
    return build_replay_fixture(
        model="HD304MSO",
        idn="KEYSIGHT TECHNOLOGIES,HD304MSO,MY12345678,10.0",
        preamble=preamble,
        raw_block=_binblock(raw_payload),
        sample_rate="1000000",
        source="unit_test_capture",
    )


def test_decode_keysight_byte_waveform_from_preamble_and_binblock():
    volts = decode_keysight_byte_waveform(
        _binblock(bytes([0, 128, 255])), "0,0,3,1,1e-6,0,0,0.01,-1.28,0"
    )

    assert volts.tolist() == pytest.approx([-1.28, 0.0, 1.27])


def test_replay_fixture_is_hash_checked_and_replay_backend_returns_raw(tmp_path):
    fixture = _fixture()
    path = write_replay_fixture(tmp_path / "fixture.json", fixture)
    loaded = load_replay_fixture(path)

    backend = ReplayBackend(loaded["log"], "scope")
    assert "HD304MSO" in backend.query("*IDN?")
    assert backend.query(":SYSTem:ERRor?").startswith("+0")
    assert backend.query(":ACQuire:SRATe:ANALog?") == "1000000"
    assert backend.query(":WAVeform:PREamble?").startswith("0,0,8")
    assert backend.query_raw(":WAVeform:DATA?") == _binblock(
        bytes([120, 124, 128, 132, 136, 132, 128, 124])
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["point_count"] = 9
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(HardwareParityError, match="payload hash mismatch"):
        load_replay_fixture(path)


def test_replay_backend_rejects_raw_response_hash_mismatch():
    fixture = _fixture()
    raw_entry = next(entry for entry in fixture["log"] if entry["type"] == "query_raw")
    raw_entry["response_base64"] = raw_entry["response_base64"][:-4] + "AAAA"

    backend = ReplayBackend(fixture["log"], "scope")
    backend.query("*IDN?")
    backend.query(":SYSTem:ERRor?")
    backend.query(":ACQuire:SRATe:ANALog?")
    backend.query(":WAVeform:PREamble?")
    with pytest.raises(ReplayMismatchError, match="SHA-256 mismatch"):
        backend.query_raw(":WAVeform:DATA?")


def test_replay_fixture_compares_to_expected_with_failure_classification():
    fixture = _fixture()
    rows = compare_replay_to_expected(fixture)
    assert rows
    assert all(row.passed for row in rows)
    assert {row.layer for row in rows} == {"analysis"}
    assert fixture["classification"]["parity_mode"] == "fixture_integrity"
    assert all("mode=fixture_integrity" in row.detail for row in rows)

    fixture["expected"]["rms"]["nominal"] += 10.0
    rows = compare_replay_to_expected(fixture)
    failed = [row for row in rows if not row.passed]
    assert len(failed) == 1
    assert failed[0].name == "rms"
    assert failed[0].layer == "sim_vs_hardware"


def test_hardware_parity_cli_writes_report(tmp_path):
    fixture_path = write_replay_fixture(tmp_path / "fixture.json", _fixture())
    out = tmp_path / "evidence"
    result = CliRunner().invoke(
        app,
        ["evidence", "hardware-parity", str(fixture_path), "--output", str(out)],
    )

    assert result.exit_code == 0
    assert "3 parity checks passed" in result.stdout
    payload = json.loads((out / "hardware_parity_report.json").read_text(encoding="utf-8"))
    assert payload["parity_mode"] == "fixture_integrity"


def test_tracked_hd304mso_fixture_replays_in_non_hardware_ci():
    fixture_path = "tests/fixtures/hardware_replay/hd304mso_lamb_capture.json"
    fixture = load_replay_fixture(fixture_path)

    rows = compare_replay_to_expected(fixture)

    assert fixture["model"] == "HD304MSO"
    assert fixture["point_count"] == 128000
    assert all(row.passed for row in rows)


def test_replay_fixture_redacts_three_field_idn() -> None:
    fixture = build_replay_fixture(
        model="WIDGETSCOPE",
        idn="ACME,WIDGETSCOPE,SERIAL123",
        preamble="0,0,3,1,1e-6,0,0,0.01,-1.28,0",
        raw_block=_binblock(bytes([120, 124, 128])),
    )

    assert fixture["log"][0]["response"] == "ACME,WIDGETSCOPE,<redacted>"
    assert "SERIAL123" not in json.dumps(fixture)
