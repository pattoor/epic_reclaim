from types import SimpleNamespace

from app.integrations.remote_screen import NoVNCProvider


RUN_RESULT = SimpleNamespace(stdout=b"\x00" * 8, stderr=b"")


def test_novnc_uses_password_file_and_serves_client(monkeypatch, tmp_path):
    commands = []

    class Process:
        def terminate(self):
            pass

        def poll(self):
            return None

        stderr = None

    monkeypatch.setattr("app.integrations.remote_screen.shutil.which", lambda _: "tool")
    monkeypatch.setattr(
        "app.integrations.remote_screen.subprocess.run",
        lambda command, **kwargs: (commands.append(command) or RUN_RESULT),
    )

    def fake_popen(command, **kwargs):
        commands.append(command)
        return Process()

    monkeypatch.setattr(
        "app.integrations.remote_screen.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        "app.integrations.remote_screen.NoVNCProvider._wait_for_port",
        lambda self, port, timeout: True,
    )

    provider = NoVNCProvider(novnc_web_dir=str(tmp_path))
    assert provider.start("session-password") == ":99"

    xvnc = next(command for command in commands if command[0] == "Xvnc")
    websockify = next(command for command in commands if command[0] == "websockify")
    store_password = commands[0]
    assert store_password[:2] == ["openssl", "enc"]
    assert "-PasswordFile" in xvnc
    assert "-localhost" in xvnc
    assert "-rfbport" in xvnc
    assert "-SecurityTypes" in xvnc and "VncAuth" in xvnc
    assert "-nopw" not in xvnc
    assert "--web" in websockify
    assert str(tmp_path) in websockify

    diagnostics = provider.diagnostics()
    assert diagnostics["tools"]["Xvnc"] is True
    assert diagnostics["tools"]["openssl"] is True
    assert diagnostics["novnc_web_dir_exists"] is True
    assert diagnostics["running"] is True

    provider.stop()


def test_novnc_reports_missing_tools(monkeypatch, tmp_path):
    monkeypatch.setattr("app.integrations.remote_screen.shutil.which", lambda tool: None)
    provider = NoVNCProvider(novnc_web_dir=str(tmp_path))
    assert provider.available() is False
    diagnostics = provider.diagnostics()
    assert diagnostics["tools"]["Xvnc"] is False
    assert provider.start("password") is None
    assert "missing tools" in (provider.diagnostics()["last_error"] or "").lower()


def test_novnc_reports_missing_novnc_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("app.integrations.remote_screen.shutil.which", lambda _: "tool")
    provider = NoVNCProvider(novnc_web_dir=str(tmp_path / "missing"))
    assert provider.available() is False
    diagnostics = provider.diagnostics()
    assert diagnostics["novnc_web_dir_exists"] is False


def test_novnc_fails_when_port_does_not_listen(monkeypatch, tmp_path):
    commands = []

    class Process:
        def terminate(self):
            pass

        def poll(self):
            return None

        stderr = None

    monkeypatch.setattr("app.integrations.remote_screen.shutil.which", lambda _: "tool")
    monkeypatch.setattr(
        "app.integrations.remote_screen.subprocess.run",
        lambda command, **kwargs: (commands.append(command) or RUN_RESULT),
    )
    monkeypatch.setattr("app.integrations.remote_screen.subprocess.Popen", lambda command, **kwargs: (commands.append(command) or Process()))

    provider = NoVNCProvider(novnc_web_dir=str(tmp_path))
    assert provider.start("session-password") is None
    assert "did not start listening" in (provider.diagnostics()["last_error"] or "")
