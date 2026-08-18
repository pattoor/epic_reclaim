from app.integrations.remote_screen import NoVNCProvider


def test_novnc_uses_password_file_and_serves_client(monkeypatch, tmp_path):
    commands = []

    class Process:
        def terminate(self):
            pass

        def poll(self):
            return None

    monkeypatch.setattr("app.integrations.remote_screen.shutil.which", lambda _: "tool")
    monkeypatch.setattr("app.integrations.remote_screen.subprocess.run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(
        "app.integrations.remote_screen.subprocess.Popen",
        lambda command, **kwargs: (commands.append(command) or Process()),
    )

    provider = NoVNCProvider(novnc_web_dir=str(tmp_path))
    assert provider.start("session-password") == ":99"

    store_password = commands[0]
    x11vnc = next(command for command in commands if "-rfbauth" in command)
    websockify = next(command for command in commands if command[0] == "websockify")
    assert store_password[:2] == ["x11vnc", "-storepasswd"]
    assert "-rfbauth" in x11vnc
    assert "-nopw" not in x11vnc
    assert "-localhost" in x11vnc
    assert "--web" in websockify
    assert str(tmp_path) in websockify

    diagnostics = provider.diagnostics()
    assert diagnostics["tools"]["Xvfb"] is True
    assert diagnostics["novnc_web_dir_exists"] is True
    assert diagnostics["running"] is True

    provider.stop()


def test_novnc_reports_missing_tools(monkeypatch, tmp_path):
    monkeypatch.setattr("app.integrations.remote_screen.shutil.which", lambda tool: None)
    provider = NoVNCProvider(novnc_web_dir=str(tmp_path))
    assert provider.available() is False
    diagnostics = provider.diagnostics()
    assert diagnostics["tools"]["Xvfb"] is False
    assert provider.start("password") is None
    assert "missing tools" in (provider.diagnostics()["last_error"] or "").lower()


def test_novnc_reports_missing_novnc_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("app.integrations.remote_screen.shutil.which", lambda _: "tool")
    provider = NoVNCProvider(novnc_web_dir=str(tmp_path / "missing"))
    assert provider.available() is False
    diagnostics = provider.diagnostics()
    assert diagnostics["novnc_web_dir_exists"] is False
