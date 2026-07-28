from __future__ import annotations

import logging

import yaml

from pytestlab.instruments.backends import sim_backend
from pytestlab.instruments.backends.sim_backend import SimBackend


def _write_profile(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "identification": "secret-profile-content",
                "simulation": {"scpi": {}},
            }
        )
    )
    return path


def test_profile_contents_are_not_printed_to_stdout(tmp_path, capsys) -> None:
    SimBackend(_write_profile(tmp_path))

    captured = capsys.readouterr()

    assert captured.out == ""
    assert "secret-profile-content" not in captured.out


def test_profile_load_logging_uses_single_propagated_record(tmp_path, caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger=sim_backend.logger.name):
        SimBackend(_write_profile(tmp_path))

    load_records = [
        record
        for record in caplog.records
        if record.getMessage().startswith("Loaded YAML profile:")
    ]
    assert len(load_records) == 1
    assert sim_backend.logger.handlers == []
    assert sim_backend.logger.propagate is True
