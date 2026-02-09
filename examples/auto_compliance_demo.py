"""
Demonstration of auto-compliance feature.

This example shows how compliance "just works" without any configuration.
"""

from pytestlab import Session


def demo_auto_compliance():
    """
    Demo: Compliance happens automatically!

    No imports from compliance module.
    No key configuration.
    No manual decorator application.

    Just use Session normally - everything is signed/audited automatically.
    """
    print("=" * 60)
    print("Auto-Compliance Demo")
    print("=" * 60)
    print()

    # STEP 1: Just use Session normally (no compliance configuration!)
    print("Creating session (compliance auto-configured)...")
    with Session("auto_compliance_demo") as session:
        # Check that compliance was auto-configured
        status = session.verify_compliance()
        print(f"Compliance enabled: {status['enabled']}")

        if status["enabled"]:
            print(f"  - Signing: {status['config']['signed']}")
            print(f"  - Auditing: {status['config']['audited']}")
            print(f"  - Timestamping: {status['config']['timestamped']}")
        print()

        # STEP 2: Register measurements (just use @session.acquire)
        print("Registering measurements (auto-wrapped with compliance)...")

        @session.acquire
        def measure_voltage():
            """This measurement will be automatically signed/audited!"""
            return {"voltage": 3.3, "unit": "V"}

        @session.acquire
        def measure_current():
            """This one too!"""
            return {"current": 0.5, "unit": "A"}

        print(f"Registered {len(session._meas_funcs)} measurements")
        print()

        # STEP 3: Verify compliance was applied
        print("Verifying compliance on measurements...")
        status = session.verify_compliance()
        for m in status["measurements"]:
            print(f"  - {m['name']}: compliance={m['compliance_applied']}")
        print()

    print("=" * 60)
    print("Demo complete!")
    print("=" * 60)
    print()
    print("Notice: We didn't:")
    print("  - Import anything from compliance module")
    print("  - Generate or configure keys")
    print("  - Add @signed or @audited decorators")
    print("  - Pass any compliance configuration")
    print()
    print("Compliance happened automatically because:")
    print("  - Session defaults to auto-configure compliance")
    print("  - Keys are auto-generated on first use")
    print("  - All measurements are auto-wrapped")


def demo_disable_compliance():
    """Show how to explicitly disable compliance."""
    print()
    print("=" * 60)
    print("Disable Compliance Demo")
    print("=" * 60)
    print()

    with Session("no_compliance", compliance=False) as session:

        @session.acquire
        def measure():
            return {"value": 42}

        status = session.verify_compliance()
        print(f"Compliance enabled: {status['enabled']}")
        print("Measurements are plain (not signed/audited)")


def demo_custom_compliance():
    """Show how to use custom compliance configuration."""
    print()
    print("=" * 60)
    print("Custom Compliance Demo")
    print("=" * 60)
    print()

    from pytestlab.compliance import ComplianceConfig

    # Use FDA regulation preset
    config = ComplianceConfig(regulation="FDA_21CFR11")

    with Session("fda_study", compliance=config) as session:

        @session.acquire
        def measure_bp():
            return {"systolic": 120, "diastolic": 80}

        status = session.verify_compliance()
        print(f"Using FDA 21 CFR Part 11 preset:")
        print(f"  - Signing: {status['config']['signed']}")
        print(f"  - Auditing: {status['config']['audited']}")
        print(f"  - Timestamping: {status['config']['timestamped']}")


def demo_key_info():
    """Show key management info."""
    print()
    print("=" * 60)
    print("Key Management Demo")
    print("=" * 60)
    print()

    try:
        from pytestlab.compliance.auto_config import get_key_info, show_compliance_status

        show_compliance_status()

        print()
        info = get_key_info()
        print(f"Key directory: {info['key_dir']}")
        print(f"Private key exists: {info['private_key_exists']}")
        print(f"Public key exists: {info['public_key_exists']}")
        if info["fingerprint"]:
            print(f"Fingerprint: {info['fingerprint']}")
    except ImportError:
        print("cryptography library not installed")
        print("Install with: pip install pytestlab[secure]")


if __name__ == "__main__":
    try:
        demo_auto_compliance()
    except Exception as e:
        print(f"Auto-compliance demo failed: {e}")

    try:
        demo_disable_compliance()
    except Exception as e:
        print(f"Disable demo failed: {e}")

    try:
        demo_custom_compliance()
    except Exception as e:
        print(f"Custom demo failed: {e}")

    try:
        demo_key_info()
    except Exception as e:
        print(f"Key info demo failed: {e}")
