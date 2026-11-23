from pytestlab._lamb_url import resolve_lamb_url


def test_url_precedence_and_legacy_scope(monkeypatch):
    monkeypatch.delenv("LAMB_SERVER", raising=False)
    monkeypatch.delenv("PYTESTLAB_LAMB_URL", raising=False)
    assert resolve_lamb_url() == "http://lamb-server:8000"
    monkeypatch.setenv("PYTESTLAB_LAMB_URL", "http://legacy")
    assert resolve_lamb_url() == "http://lamb-server:8000"
    monkeypatch.setenv("LAMB_SERVER", "http://env")
    assert resolve_lamb_url() == "http://env"
    assert resolve_lamb_url(profile_url="http://profile") == "http://profile"
    assert resolve_lamb_url("http://explicit/", profile_url="http://profile") == "http://explicit"
    monkeypatch.setenv("LAMB_SERVER", "")
    assert resolve_lamb_url() == "http://lamb-server:8000"


def test_lamb_list_resolves_environment_at_invocation(monkeypatch):
    import httpx
    from typer.testing import CliRunner

    from pytestlab.cli import app

    calls = []
    real_client = httpx.Client

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"active": [], "inactive": []})

    monkeypatch.setattr(
        "httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setenv("LAMB_SERVER", "http://changed-after-import:8000")
    result = CliRunner().invoke(app, ["lamb", "list"])
    assert result.exit_code == 0, result.output
    assert calls == ["http://changed-after-import:8000/list_resources"]
