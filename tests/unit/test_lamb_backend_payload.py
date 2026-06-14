from pytestlab.instruments.backends.lamb import LambBackend


def test_lamb_backend_payload_includes_timeout_budget():
    backend = LambBackend(
        address="USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        timeout_ms=300_000,
    )

    assert backend._instrument_payload("*IDN?") == {
        "visa_string": "USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        "command": "*IDN?",
        "timeout_ms": 300_000,
    }


def test_lamb_backend_set_timeout_updates_payload_budget():
    backend = LambBackend(address="USB::2A8D::9007::MXR404A::MY62310227::INSTR")

    backend.set_timeout(12_345)

    assert backend._instrument_payload(":SYSTem:ERRor?")["timeout_ms"] == 12_345


def test_lamb_backend_default_payload_budget_is_30_seconds():
    backend = LambBackend(address="USB::2A8D::9007::MXR404A::MY62310227::INSTR")

    assert backend._instrument_payload("*IDN?")["timeout_ms"] == 30_000


def test_lamb_backend_none_timeout_uses_default_30_seconds():
    backend = LambBackend(
        address="USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        timeout_ms=None,
    )

    assert backend._instrument_payload("*IDN?")["timeout_ms"] == 30_000


def test_lamb_backend_http_timeout_exceeds_payload_budget():
    backend = LambBackend(
        address="USB::2A8D::9007::MXR404A::MY62310227::INSTR",
        timeout_ms=30_000,
    )

    assert backend._instrument_payload("*IDN?")["timeout_ms"] == 30_000
    assert backend._http_timeout_sec() == 35.0
    assert backend._http_timeout_sec() > backend._instrument_payload("*IDN?")["timeout_ms"] / 1000
