import concurrent.futures
import lzma
import pickle
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl
from polars.testing import assert_frame_equal

from pytestlab.experiments import Database
from pytestlab.experiments import Experiment
from pytestlab.experiments import MeasurementResult


class TestDatabase(unittest.TestCase):
    def setUp(self):
        """Set up test database and other initial conditions."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_database"
        self.db = Database(self.db_path)

    def tearDown(self):
        """Tear down test database and other cleanup."""
        self.db.close()
        self.temp_dir.cleanup()

    def test_store_and_retrieve_measurement(self):
        """Test storing and retrieving a MeasurementResult."""
        values = pl.DataFrame(
            {
                "index": pl.Series([1, 2, 3], dtype=pl.Int64),
                "reading": pl.Series([1.25, 2.5, 3.75], dtype=pl.Float32),
                "label": pl.Series(["low", "mid", "high"], dtype=pl.String),
                "valid": pl.Series([True, False, True], dtype=pl.Boolean),
            }
        )
        meas = MeasurementResult(
            instrument="DMM",
            values=values,
            measurement_type="voltage",
            units="V",
            timestamp=datetime.now().timestamp(),
        )
        codename = self.db.store_measurement(None, meas)
        retrieved = self.db.retrieve_measurement(codename)
        self.assertEqual(retrieved.instrument, meas.instrument)
        self.assertEqual(retrieved.measurement_type, meas.measurement_type)
        self.assertEqual(retrieved.units, meas.units)
        self.assertIsInstance(retrieved.values, pl.DataFrame)
        assert_frame_equal(retrieved.values, values)

    def test_legacy_numpy_and_polars_blobs_remain_readable(self):
        """Test untagged blobs written by earlier releases remain readable."""
        numpy_values = np.array([[1.5, 2.5]], dtype=np.float32)
        metadata = {
            "dtype": str(numpy_values.dtype),
            "shape": numpy_values.shape,
            "compressed": True,
        }
        metadata_bytes = pickle.dumps(metadata)
        numpy_blob = (
            len(metadata_bytes).to_bytes(4, "little")
            + metadata_bytes
            + lzma.compress(numpy_values.tobytes())
        )
        polars_values = pl.DataFrame(
            {"sample": pl.Series([1, 2], dtype=pl.UInt16), "state": ["on", "off"]}
        )
        polars_blob = lzma.compress(polars_values.write_ipc(None).getvalue())

        restored_numpy = self.db._convert_numpy(numpy_blob)
        restored_polars = self.db._convert_numpy(polars_blob)

        np.testing.assert_array_equal(restored_numpy, numpy_values)
        self.assertIsInstance(restored_polars, pl.DataFrame)
        assert_frame_equal(restored_polars, polars_values)

    def test_list_and_search_measurements(self):
        """Test listing and searching for measurements."""
        values = pl.DataFrame({"b": np.arange(3)}, schema={"b": pl.Int64})
        meas = MeasurementResult(
            instrument="Scope",
            values=values,
            measurement_type="current",
            units="A",
            timestamp=datetime.now().timestamp(),
        )
        codename = self.db.store_measurement(None, meas)
        all_codes = self.db.list_measurements()
        self.assertIn(codename, all_codes)
        results = self.db.search_measurements("Scope")
        self.assertTrue(any(r["codename"] == codename for r in results))

    def test_experiment_storage(self):
        """Test storing and retrieving an Experiment."""
        experiment = Experiment("Test", "test experiment")
        data_values = pl.DataFrame(
            {"a": np.arange(1, 1000), "b": np.arange(1, 1000)},
            schema={"a": pl.UInt64, "b": pl.UInt64},
        )
        data = MeasurementResult(
            instrument="fake", values=data_values, measurement_type="fake", units="l"
        )
        experiment.add_trial(data)
        codename = self.db.store_experiment(None, experiment)
        retrieved = self.db.retrieve_experiment(codename)
        self.assertEqual(retrieved.name, experiment.name)
        self.assertEqual(retrieved.description, experiment.description)
        self.assertEqual(retrieved.data.schema, experiment.data.schema)
        self.assertEqual(len(retrieved), len(experiment))

    def test_list_and_search_experiments(self):
        """Test listing and searching for experiments."""
        experiment = Experiment("SearchExp", "desc")
        experiment.add_parameter("Current", "A")
        experiment.add_trial({"Current": 2.34}, Current=2.34)
        codename = self.db.store_experiment(None, experiment)
        all_codes = self.db.list_experiments()
        self.assertIn(codename, all_codes)
        results = self.db.search_experiments("SearchExp")
        self.assertTrue(any(r["codename"] == codename for r in results))

    def test_overwrite_keeps_full_text_indexes_consistent(self):
        """Test updates remove old search terms and index the replacement."""
        first_experiment = Experiment("obsoleteexperiment", "first description")
        second_experiment = Experiment("currentexperiment", "replacement description")
        self.db.store_experiment("experiment-key", first_experiment)
        self.db.store_experiment("experiment-key", second_experiment)

        self.assertEqual(self.db.search_experiments("obsoleteexperiment"), [])
        experiment_matches = self.db.search_experiments("currentexperiment")
        self.assertEqual([match["codename"] for match in experiment_matches], ["experiment-key"])

        first_measurement = MeasurementResult(
            instrument="DMM",
            values=np.array([1.0]),
            measurement_type="obsoletevoltage",
            units="V",
        )
        second_measurement = MeasurementResult(
            instrument="DMM",
            values=np.array([2.0]),
            measurement_type="currentvoltage",
            units="V",
        )
        self.db.store_measurement("measurement-key", first_measurement)
        self.db.store_measurement("measurement-key", second_measurement)

        self.assertEqual(self.db.search_measurements("obsoletevoltage"), [])
        measurement_matches = self.db.search_measurements("currentvoltage")
        self.assertEqual([match["codename"] for match in measurement_matches], ["measurement-key"])

    def test_concurrent_measurement_writes_are_lossless(self):
        """Test one database instance supports bounded parallel writes."""
        write_count = 200

        def write_measurement(index):
            measurement = MeasurementResult(
                instrument=f"DMM-{index % 4}",
                values=np.array([index], dtype=np.int64),
                measurement_type="parallel-voltage",
                units="V",
            )
            return self.db.store_measurement(None, measurement)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            codenames = list(executor.map(write_measurement, range(write_count)))

        self.assertEqual(len(codenames), write_count)
        self.assertEqual(set(self.db.list_measurements()), set(codenames))
        self.assertEqual(self.db.get_stats()["measurements"], write_count)

    def test_stats_and_vacuum(self):
        """Test database stats and vacuuming."""
        experiment = Experiment("StatsExp", "desc")
        experiment.add_parameter("X", "unit")
        experiment.add_trial({"X": 1}, X=1)
        self.db.store_experiment(None, experiment)
        stats = self.db.get_stats()
        self.assertGreaterEqual(stats["experiments"], 1)
        self.db.vacuum()  # Should not raise


def test_legacy_fts_triggers_are_migrated_and_indexes_rebuilt(tmp_path):
    """Legacy non-rowid triggers are replaced and stale FTS indexes rebuilt."""
    db_stem = tmp_path / "legacy_fts"
    conn = sqlite3.connect(db_stem.with_suffix(".db"))
    conn.executescript("""
        CREATE TABLE experiments (
            codename TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            notes TEXT,
            data PLBLOB,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        );
        CREATE VIRTUAL TABLE experiments_fts USING fts5(
            codename, name, description, notes, content='experiments'
        );
        CREATE TRIGGER experiments_fts_insert AFTER INSERT ON experiments BEGIN
            INSERT INTO experiments_fts(codename, name, description, notes)
            VALUES (new.codename, new.name, new.description, new.notes);
        END;
        CREATE TRIGGER experiments_fts_delete AFTER DELETE ON experiments BEGIN
            DELETE FROM experiments_fts WHERE codename = old.codename;
        END;
        CREATE TRIGGER experiments_fts_update AFTER UPDATE ON experiments BEGIN
            UPDATE experiments_fts SET name = new.name WHERE codename = new.codename;
        END;

        CREATE TABLE instruments (
            instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE measurements (
            codename TEXT PRIMARY KEY,
            instrument_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            value_data NPBLOB NOT NULL,
            units TEXT,
            measurement_type TEXT,
            notes TEXT,
            metadata TEXT
        );
        CREATE VIRTUAL TABLE measurements_fts USING fts5(
            codename, measurement_type, notes, content='measurements'
        );
        CREATE TRIGGER measurements_fts_insert AFTER INSERT ON measurements BEGIN
            INSERT INTO measurements_fts(codename, measurement_type, notes)
            VALUES (new.codename, new.measurement_type, new.notes);
        END;
        CREATE TRIGGER measurements_fts_delete AFTER DELETE ON measurements BEGIN
            DELETE FROM measurements_fts WHERE codename = old.codename;
        END;
        CREATE TRIGGER measurements_fts_update AFTER UPDATE ON measurements BEGIN
            UPDATE measurements_fts SET measurement_type = new.measurement_type
            WHERE codename = new.codename;
        END;

        INSERT INTO experiments(rowid, codename, name, description)
        VALUES (10, 'legacy-experiment', 'legacyoptics', 'legacy experiment');
        INSERT INTO instruments(instrument_id, name) VALUES (1, 'LegacyScope');
        INSERT INTO measurements(rowid, codename, instrument_id, value_data, measurement_type)
        VALUES (20, 'legacy-measurement', 1, x'00', 'legacycurrent');
    """)
    conn.close()

    with Database(db_stem) as db:
        assert [row["codename"] for row in db.search_experiments("legacyoptics")] == [
            "legacy-experiment"
        ]
        assert [row["codename"] for row in db.search_measurements("legacycurrent")] == [
            "legacy-measurement"
        ]
        trigger_sql = {
            row[0]: row[1]
            for row in db._get_connection().execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
            )
        }

    assert "new.rowid" in trigger_sql["experiments_fts_insert"]
    assert "'delete'" in trigger_sql["experiments_fts_update"]
    assert "new.rowid" in trigger_sql["measurements_fts_insert"]
    assert "'delete'" in trigger_sql["measurements_fts_update"]


if __name__ == "__main__":
    unittest.main()
