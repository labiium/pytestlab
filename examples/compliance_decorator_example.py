"""
Example: Using compliance decorators with implicit application.

This demonstrates the new pattern:
- No monkey-patching
- No explicit decorator spam
- Centralized configuration
- Automatic application to all measurements
"""

from pytestlab import Session
from pytestlab.compliance import ComplianceConfig

# =============================================================================
# EXAMPLE 1: Basic Signing (Implicit Application)
# =============================================================================


def example_basic_signing():
    """All measurements automatically signed."""

    # Configure compliance once at session level
    from pytestlab.compliance.paths import private_key_path

    config = ComplianceConfig(signing={"key_file": str(private_key_path("test.pem"))})

    with Session("signed_experiment", compliance=config) as session:
        # These are automatically signed - no @signed decorator needed!
        @session.measure
        def measure_voltage(dmm):
            return {"voltage": dmm.read_voltage()}

        @session.measure
        def measure_current(dmm):
            return {"current": dmm.read_current()}

        exp = session.run()

    # Results are CompliantResult objects with signatures
    for trial in exp.trials:
        for measurement in trial.measurements:
            print(f"Measurement: {measurement.data}")
            print(f"Signature: {measurement.signature.value[:32]}...")
            print(f"Key: {measurement.signature.key_fingerprint}")


# =============================================================================
# EXAMPLE 2: Full Compliance (FDA Mode)
# =============================================================================


def example_fda_compliance():
    """FDA 21 CFR Part 11 compliant measurements."""

    # Use regulation preset - all requirements pre-configured
    config = ComplianceConfig(regulation="FDA_21CFR11")

    with Session("fda_study_001", compliance=config) as session:
        # All measurements are:
        # - Signed with FDA key
        # - Audited to FDA audit trail
        # - Timestamped by external TSA

        @session.measure
        def blood_pressure(patient_id):
            return {
                "patient_id": patient_id,
                "systolic": 120,
                "diastolic": 80,
                "timestamp": "2024-01-15T09:30:00Z",
            }

        @session.measure
        def heart_rate(patient_id):
            return {"patient_id": patient_id, "bpm": 72}

        exp = session.run()

    # Verify compliance
    for trial in exp.trials:
        for measurement in trial.measurements:
            # Verify signature
            assert measurement.signature is not None
            assert measurement.audit_record is not None
            assert measurement.timestamp_token is not None

            # Full verification
            verification = measurement.verify(trust_anchor="company_ca.pem")
            assert verification.valid, f"Compliance failed: {verification.issues}"


# =============================================================================
# EXAMPLE 3: Audit Only (No Signing)
# =============================================================================


def example_audit_only():
    """Just audit trail, no cryptographic signing."""

    config = ComplianceConfig(
        signing=None,  # No signing
        audit={"audit_db": "audit.sqlite"},
        timestamp=None,  # No timestamps
    )

    with Session("audit_only", compliance=config) as session:

        @session.measure
        def temperature_reading(thermometer):
            return {"temp_c": thermometer.read()}

        exp = session.run()

    # Results have audit records but no signatures
    for trial in exp.trials:
        for measurement in trial.measurements:
            assert measurement.audit_record is not None
            assert measurement.signature is None  # No signing


# =============================================================================
# EXAMPLE 4: Mixed Session (Some Signed, Some Not)
# =============================================================================


def example_mixed_compliance():
    """Most measurements signed, but some exempt."""

    from pytestlab.compliance.paths import private_key_path

    config = ComplianceConfig(signing={"key_file": str(private_key_path("prod.pem"))})

    with Session("mixed", compliance=config) as session:
        # This gets automatically signed
        @session.measure
        def critical_measurement(dmm):
            return {"voltage": dmm.read_voltage()}

        # How to exempt? Use raw registration
        def quick_check(dmm):
            return {"quick_read": dmm.read_voltage()}

        # Register without compliance wrapper
        session._meas_funcs.append(("quick_check", quick_check))

        session.run()


# =============================================================================
# EXAMPLE 5: Verification After the Fact
# =============================================================================


def example_verification():
    """Verify compliance of saved experiments."""

    from pytestlab import load_experiment

    # Load previously saved experiment
    exp = load_experiment("results/fda_study_001.json")

    # Verify all measurements
    for trial in exp.trials:
        for measurement in trial.measurements:
            verification = measurement.verify(trust_anchor="company_ca.pem")

            if verification.valid:
                print(f"✓ {measurement.data}: VALID")
                print(f"  Signed by: {measurement.signature.key_fingerprint}")
                print(f"  At: {measurement.signature.timestamp}")
            else:
                print(f"✗ {measurement.data}: INVALID")
                for issue in verification.issues:
                    print(f"  - {issue}")


# =============================================================================
# EXAMPLE 6: Checking Compliance Status
# =============================================================================


def example_check_status():
    """Check compliance configuration of a session."""

    config = ComplianceConfig(
        regulation="FDA_21CFR11",
        signing={"key_file": "custom_key.pem"},  # Override preset
    )

    with Session("status_check", compliance=config) as session:

        @session.measure
        def m1(dmm):
            return {"v": 1.0}

        @session.measure
        def m2(dmm):
            return {"v": 2.0}

        # Check compliance status before running
        status = session.verify_compliance()

        print("Compliance Status:")
        print(f"  Enabled: {status['enabled']}")
        print(f"  Signed: {status['config']['signed']}")
        print(f"  Audited: {status['config']['audited']}")
        print(f"  Timestamped: {status['config']['timestamped']}")

        for m in status["measurements"]:
            print(f"  - {m['name']}: compliance={m['compliance_applied']}")


# =============================================================================
# EXAMPLE 7: Configuration from File
# =============================================================================


def example_config_from_file():
    """Load compliance config from pyproject.toml or JSON."""

    import tomllib

    # Load from pyproject.toml
    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)

    compliance_settings = config["tool"]["pytestlab"]["compliance"]

    # Create config from dict
    compliance_config = ComplianceConfig(**compliance_settings)

    with Session("from_config", compliance=compliance_config) as session:

        @session.measure
        def measurement(dmm):
            return {"v": dmm.read_voltage()}

        session.run()


# =============================================================================
# EXAMPLE 8: Convenience Function
# =============================================================================


def example_convenience_function():
    """Using create_compliant_session shortcut."""

    from pytestlab.compliance import create_compliant_session

    # Just specify regulation name
    with create_compliant_session("quick_fda", compliance="FDA_21CFR11") as session:

        @session.measure
        def m1(dmm):
            return {"v": 1.0}

        session.run()

    # Or with dict config
    with create_compliant_session(
        "quick_custom",
        compliance={
            "signing": {"key_file": "keys/prod.pem"},
            "audit": {"audit_db": "audit.sqlite"},
        },
    ) as session:

        @session.measure
        def m2(dmm):
            return {"v": 2.0}

        session.run()


# =============================================================================
# COMPARISON: Old vs New Pattern
# =============================================================================


def comparison_old_vs_new():
    """
    OLD PATTERN (Monkey Patching):
        import pytestlab.compliance  # Magic happens here!

        with Session("test") as session:
            @session.measure
            def m1(dmm):
                return {"v": 1.0}

    PROBLEMS:
    - Just importing changes global behavior
    - Can't tell if compliance is active
    - Can't configure per-session
    - Can't exempt specific measurements
    - Hard to test

    NEW PATTERN (Implicit Decorators):
        config = ComplianceConfig(signing={"key_file": "key.pem"})

        with Session("test", compliance=config) as session:
            @session.measure  # Auto-wrapped based on config
            def m1(dmm):
                return {"v": 1.0}

    ADVANTAGES:
    - Explicit configuration
    - Per-session control
    - No global state
    - Easy to verify status
    - Testable
    - No monkey patching!
    """
    pass


if __name__ == "__main__":
    print("Compliance decorator examples loaded.")
    print("Run individual examples to see them in action.")
