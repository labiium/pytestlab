"""
Tests for auto-compliance features.

These tests verify that:
1. Compliance is automatically configured by default
2. Keys are auto-generated on first use
3. Measurements are automatically wrapped with compliance
4. Compliance can be explicitly disabled
5. Custom compliance configurations work
"""

import importlib.util
import os
from unittest import mock

import pytest

from pytestlab import Session
from pytestlab.compliance import ComplianceConfig
from pytestlab.compliance.auto_config import ensure_compliance_config
from pytestlab.compliance.auto_config import get_key_info
from pytestlab.compliance.auto_config import is_compliance_available


@pytest.fixture
def isolated_compliance_dir(tmp_path):
    """Create isolated compliance directory for testing."""
    home = tmp_path / "home"
    home.mkdir()

    # Redirect compliance state to a temp directory
    state_dir = home / "state"

    with mock.patch.dict(
        os.environ,
        {
            "HOME": str(home),
            "PYTESTLAB_STATE_DIR": str(state_dir),
        },
        clear=False,
    ):
        yield home


class TestAutoComplianceConfiguration:
    """Test auto-configuration of compliance infrastructure."""

    def test_auto_generates_keys_on_first_use(self, isolated_compliance_dir):
        """Keys should be auto-generated when compliance is first used."""
        home = isolated_compliance_dir
        key_dir = home / "state" / "keys"

        # Keys shouldn't exist yet
        assert not key_dir.exists() or not any(key_dir.iterdir())

        # Create session (should auto-configure)
        with Session("test"):
            pass

        # Keys should now exist
        assert key_dir.exists()
        assert (key_dir / "auto_generated.pem").exists()
        assert (key_dir / "auto_generated.pub").exists()

    def test_reuses_existing_keys(self, isolated_compliance_dir):
        """Should reuse existing keys, not regenerate."""
        home = isolated_compliance_dir

        # First session creates keys
        with Session("test1"):
            pass

        key_dir = home / "state" / "keys"
        private_key = key_dir / "auto_generated.pem"
        first_key_content = private_key.read_bytes()

        # Second session should reuse same keys
        with Session("test2"):
            pass

        second_key_content = private_key.read_bytes()
        assert first_key_content == second_key_content

    def test_compliance_available_check(self):
        """Test compliance availability detection."""
        # Should be available if cryptography installed
        available = is_compliance_available()

        assert available is (importlib.util.find_spec("cryptography") is not None)


class TestSessionComplianceIntegration:
    """Test compliance integration with MeasurementSession."""

    def test_session_auto_enables_compliance(self, isolated_compliance_dir):
        """Session should automatically enable compliance by default."""
        with Session("test") as session:
            # Compliance should be configured
            assert session._compliance_config is not None
            assert session._compliance_wrapper is not None

    def test_session_can_disable_compliance(self, isolated_compliance_dir):
        """Session should allow explicit disabling of compliance."""
        with Session("test", compliance=False) as session:
            assert session._compliance_config is None
            assert session._compliance_wrapper is None

    def test_session_accepts_custom_config(self, isolated_compliance_dir):
        """Session should accept custom ComplianceConfig."""
        # First ensure keys exist
        with Session("temp") as _:
            pass

        home = isolated_compliance_dir
        config = ComplianceConfig(
            signing={"key_file": str(home / "state" / "keys" / "auto_generated.pem")},
            audit=None,  # Disable audit
            timestamp=None,  # Disable timestamp
        )

        with Session("test", compliance=config) as session:
            assert session._compliance_config is not None
            assert session._compliance_config.signing is not None
            assert session._compliance_config.audit is None

    def test_disabled_custom_config_does_not_create_wrapper(self):
        config = ComplianceConfig(enabled=False)

        with Session("test", compliance=config) as session:
            assert session._compliance_mode == "disabled"
            assert session._compliance_config is config
            assert session._compliance_wrapper is None
            assert session.verify_compliance()["enabled"] is False

    def test_verify_compliance_status_disabled(self, isolated_compliance_dir):
        """Test verify_compliance when disabled."""
        with Session("test", compliance=False) as session:
            status = session.verify_compliance()

            assert status["enabled"] is False
            assert "message" in status

    def test_verify_compliance_status_enabled(self, isolated_compliance_dir):
        """Test verify_compliance when enabled."""
        with Session("test") as session:

            @session.acquire
            def measure1():
                return {"value": 1}

            @session.acquire
            def measure2():
                return {"value": 2}

            status = session.verify_compliance()

            assert status["enabled"] is True
            assert "config" in status
            assert "measurements" in status
            assert len(status["measurements"]) == 2

    def test_required_compliance_fails_closed_on_component_initialization_error(
        self, isolated_compliance_dir, monkeypatch
    ):
        monkeypatch.setattr(
            "pytestlab.compliance.session.ComplianceConfig._initialize_from_configs",
            lambda self: self._initialization_errors.append("signer unavailable"),
        )

        with pytest.raises(RuntimeError, match="Required compliance setup failed"):
            Session("test")

    def test_best_effort_compliance_continues_on_setup_error(
        self, isolated_compliance_dir, monkeypatch
    ):
        monkeypatch.setattr(
            "pytestlab.compliance.session.ComplianceConfig._initialize_from_configs",
            lambda self: self._initialization_errors.append("signer unavailable"),
        )

        session = Session("test", compliance="best_effort")

        assert session._compliance_mode == "best_effort"
        assert session._compliance_config is not None

    def test_verify_compliance_uses_actual_component_readiness(self):
        session = Session("test", compliance=False)
        session._compliance_config = ComplianceConfig(enabled=True)
        status = session.verify_compliance()

        assert status["config"] == {
            "signed": False,
            "audited": False,
            "timestamped": False,
        }


class TestMeasurementWrapping:
    """Test that measurements are automatically wrapped."""

    def test_measurement_auto_wrapped(self, isolated_compliance_dir):
        """Measurements should be automatically wrapped with compliance."""
        # Note: This test requires cryptography to be installed
        pytest.importorskip("cryptography")

        with Session("test") as session:

            @session.acquire
            def measure():
                return {"value": 42}

            # The stored function should be wrapped
            assert len(session._meas_funcs) == 1
            name, wrapped_func = session._meas_funcs[0]

            assert name == "measure"
            # Session-level wrapper should be enabled
            assert session._compliance_wrapper is not None

    def test_measurement_not_wrapped_when_disabled(self, isolated_compliance_dir):
        """Measurements should not be wrapped when compliance disabled."""
        with Session("test", compliance=False) as session:

            @session.acquire
            def measure():
                return {"value": 42}

            # The stored function should NOT be wrapped
            assert len(session._meas_funcs) == 1
            name, func = session._meas_funcs[0]

            assert name == "measure"
            assert session._compliance_wrapper is None


class TestEnvironmentVariables:
    """Test environment variable overrides."""

    def test_disable_via_environment(self, isolated_compliance_dir):
        """Compliance can be disabled via environment variable."""
        with mock.patch.dict(os.environ, {"PYTESTLAB_COMPLIANCE_DISABLED": "true"}):
            with Session("test") as session:
                # Should be disabled despite default auto-config
                assert session._compliance_config is None

    def test_custom_key_via_environment(self, isolated_compliance_dir):
        """Custom key can be specified via environment."""
        home = isolated_compliance_dir
        custom_key = home / "custom_key.pem"
        custom_key.write_text("dummy key content")

        with mock.patch.dict(os.environ, {"PYTESTLAB_KEY_FILE": str(custom_key)}):
            config = ensure_compliance_config()
            assert config["signing"]["key_file"] == str(custom_key)


class TestKeyManagement:
    """Test key generation and management."""

    def test_key_permissions(self, isolated_compliance_dir):
        """Generated keys should have correct permissions."""
        pytest.importorskip("cryptography")

        home = isolated_compliance_dir

        # Trigger key generation
        with Session("test") as _:
            pass

        key_dir = home / "state" / "keys"
        private_key = key_dir / "auto_generated.pem"
        public_key = key_dir / "auto_generated.pub"

        # Private key should be restricted (owner read/write only)
        private_stat = private_key.stat()
        assert private_stat.st_mode & 0o777 == 0o600

        # Public key can be readable
        public_stat = public_key.stat()
        assert public_stat.st_mode & 0o444 == 0o444  # Readable by all

    def test_get_key_info(self, isolated_compliance_dir):
        """Test key info retrieval."""
        pytest.importorskip("cryptography")

        # Before key generation
        info_before = get_key_info()
        assert info_before["private_key_exists"] is False
        assert info_before["fingerprint"] is None

        # Generate keys
        with Session("test") as _:
            pass

        # After key generation
        info_after = get_key_info()
        assert info_after["private_key_exists"] is True
        assert info_after["public_key_exists"] is True
        assert info_after["fingerprint"] is not None
        assert info_after["fingerprint"].startswith("SHA256:")


class TestBackwardCompatibility:
    """Test backward compatibility with non-compliance usage."""

    def test_session_works_without_compliance(self):
        """Session should work normally when compliance disabled."""
        with Session("test", compliance=False) as session:

            @session.acquire
            def measure():
                return {"value": 1.0}

            # Should be able to run without any compliance infrastructure
            # Note: We can't actually run without instruments, but we can verify
            # the session structure is correct
            assert len(session._meas_funcs) == 1


class TestComplianceConfigPresets:
    """Test regulation preset configurations."""

    def test_fda_21cfr11_preset(self, isolated_compliance_dir):
        """Test FDA 21 CFR Part 11 preset."""
        pytest.importorskip("cryptography")

        # Generate keys first
        with Session("temp") as _:
            pass

        config = ComplianceConfig(regulation="FDA_21CFR11")

        assert config.signing is not None
        assert config.audit is not None
        assert config.timestamp is not None
        # FDA requires external TSA
        assert config.timestamp is not None
        assert config.timestamp.get("local_fallback") is False

    def test_iso17025_preset(self, isolated_compliance_dir):
        """Test ISO 17025 preset."""
        pytest.importorskip("cryptography")

        # Generate keys first
        with Session("temp") as _:
            pass

        config = ComplianceConfig(regulation="ISO17025")

        assert config.signing is not None
        assert config.audit is not None
        # ISO allows local timestamp
        assert config.timestamp is not None
        assert config.timestamp.get("local_fallback") is True


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
