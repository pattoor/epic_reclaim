from app.integrations.remote_screen import NoVNCProvider


def test_novnc_uses_password_file_and_serves_client(monkeypatch, tmp_path):
    commands = []

    class Process:
        def terminate(self):
            pass

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

    provider.stop()
