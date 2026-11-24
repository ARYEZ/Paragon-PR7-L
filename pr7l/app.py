"""Start PR7-L.

    PR7-L.exe [folder | files ...]     open them (Mp3tag's /fp:<folder> works too)
    PR7-L.exe --explorer PATH          from Explorer's "PR7-L" item: PR7-Ls started together (one per selected
                                       file) hand their paths to the first, so one selection is one window
    PR7-L.exe --register | --unregister    the Explorer item (this user only)
    PR7-L.exe --dump OUT.json FILES...     write the files' tags as JSON (CI checks the built program with it)
"""

from __future__ import annotations

import os
import sys

COLLECT_MS = 450


def _server_name() -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"pr7l-{user}-explorer"


def collect(paths: list[str]) -> list[str] | None:
    """Gather the paths of PR7-Ls started at the same moment. Returns all of them (we're the first), or
    None (we handed ours over: exit). The same scheme as PR7-Z's fallback menu."""
    from PySide6.QtCore import QByteArray, QElapsedTimer
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    name = _server_name()
    for _ in range(3):
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(150):
            sock.write(QByteArray("\n".join(paths).encode("utf-8")))
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()
            return None
        server = QLocalServer()
        if server.listen(name):
            break
        QLocalServer.removeServer(name)
    else:
        return paths
    got = list(paths)
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < COLLECT_MS:
        server.waitForNewConnection(50)  # PySide returns (ok, timed_out): check for a connection instead
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is None:
                break
            data = bytes(conn.readAll())
            while conn.state() == QLocalSocket.ConnectedState and conn.waitForReadyRead(300):
                data += bytes(conn.readAll())
            data += bytes(conn.readAll())
            got += [p for p in data.decode("utf-8").split("\n") if p]
            timer.restart()
    server.close()
    return list(dict.fromkeys(got))


def parse(argv: list[str]) -> tuple[str | None, list[str]]:
    action, paths = None, []
    for a in argv:
        if a in ("--explorer", "--register", "--unregister", "--register-menu", "--unregister-menu", "--version"):
            action = a
        elif a.lower().startswith("/fp:"):  # Mp3tag's own switch, so its shortcuts keep working
            paths.append(a[4:])
        else:
            paths.append(a)
    return action, [os.path.abspath(p) for p in paths if os.path.exists(p)]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    action, paths = parse(argv)
    if action == "--version":
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--dump"] and len(argv) > 2:
        import json
        from . import tags
        out = {}
        for p in argv[2:]:
            try:
                t = tags.read(p)
                out[p] = {"fields": t.fields, "pictures": len(t.pictures), "tag": t.tag_label, "codec": t.info.codec}
            except Exception as e:  # noqa: BLE001 - reported in the output
                out[p] = {"error": str(e)}
        with open(argv[1], "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        return 0
    if action in ("--register", "--unregister", "--register-menu", "--unregister-menu"):
        from . import shell
        return shell.run(action)
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-L")
    if action == "--explorer":
        paths = collect(paths)
        if paths is None:
            return 0
    from .main_window import MainWindow
    theme.set_finish(settings.get("finish", "obsidian"))
    theme.load_fonts()
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    w = MainWindow(paths)
    w.show()
    from . import update_ui
    update_ui.start(w)  # a check for updates, once a day
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
