import json

import httpx
import pytest
from typer.testing import CliRunner

from pytestlab.cli import app


@pytest.mark.parametrize(
    "payload,status,success",
    [
        (
            {
                "devices": [
                    {"resource_string": "local:/dev/video0", "label": "UGREEN Camera"},
                    {"resource_string": "local:/dev/video2", "label": "UGREEN Camera 2K"},
                ]
            },
            200,
            True,
        ),
        ({"devices": []}, 200, True),
        ({"devices": [{"resource_string": ""}]}, 200, False),
        ({"devices": {}}, 200, False),
        ({"error": "unavailable"}, 503, False),
    ],
)
def test_camera_discover_without_bench(monkeypatch, payload, status, success):
    calls = []
    real_client = httpx.Client

    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(
        "pytestlab.cli.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = CliRunner().invoke(app, ["camera", "discover", "--url", "http://lamb.test", "--json"])
    assert result.exit_code == (0 if success else 1), result.output
    assert calls == [("GET", "/webcams")]
    if success:
        assert json.loads(result.output) == payload["devices"]
    else:
        assert "Error:" in result.output


@pytest.mark.parametrize(
    "args", [["--url", "file:///dev/video0"], ["--url", "http://lamb.test", "--timeout-ms", "0"]]
)
def test_discovery_rejects_invalid_configuration_before_network(monkeypatch, args):
    def fail(**kwargs):
        pytest.fail("must reject before networking")

    monkeypatch.setattr("pytestlab.cli.httpx.Client", fail)
    result = CliRunner().invoke(app, ["camera", "discover", *args])
    assert result.exit_code == 1


@pytest.mark.parametrize(
    "env,explicit,expected",
    [
        ("http://env.test:8000", None, "http://env.test:8000/webcams"),
        ("http://env.test:8000", "http://override.test:8000", "http://override.test:8000/webcams"),
        (None, None, "http://lamb-server:8000/webcams"),
    ],
)
def test_discovery_url_fallback(monkeypatch, env, explicit, expected):
    monkeypatch.delenv("LAMB_SERVER", raising=False)
    if env:
        monkeypatch.setenv("LAMB_SERVER", env)
    calls = []
    real_client = httpx.Client

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"devices": []})

    monkeypatch.setattr(
        "pytestlab.cli.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    args = ["camera", "discover", "--json"]
    if explicit:
        args += ["--url", explicit]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert calls == [expected]
