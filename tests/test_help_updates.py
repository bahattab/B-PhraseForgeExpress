"""Help > User guide and Check for updates (no network: GitHub is faked)."""
import io
import json
import urllib.error

import pytest

from phraseforge import __version__, updates
from phraseforge.ui.help_viewer import guide_path


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(payload=None, code=None):
    def op(req, timeout=0):
        if code:
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return _Resp(json.dumps(payload).encode())
    return op


def test_version_compare():
    assert updates.is_newer("0.10.0", "0.9.9")
    assert not updates.is_newer("v0.3.0", "0.3.0")


def test_latest_release_parsing_and_none():
    rel = updates.latest_release(opener=_opener({"tag_name": "v9.0.0", "html_url": "https://example.invalid/r"}))
    assert rel["version"] == "9.0.0" and rel["url"] == "https://example.invalid/r"
    assert updates.latest_release(opener=_opener(code=404)) is None
    with pytest.raises(OSError):
        updates.latest_release(opener=_opener(code=500))


def test_arabic_guide_exists_and_mentions_features():
    p = guide_path("ar")
    assert p.name == "USER_GUIDE.ar.md"
    text = p.read_text(encoding="utf-8")
    for needle in ("Ctrl+Alt+Space", "PhraseExpress", "-calendar hijri", "Ctrl + Shift"):
        assert needle in text
    assert guide_path("en").name == "README.md"


def test_main_window_help_and_updates(qtbot_free_app, tmp_path):
    from phraseforge.db import Store
    from phraseforge.ui import i18n
    from phraseforge.ui.main_window import MainWindow
    s = Store(tmp_path / "t.db")
    try:
        mw = MainWindow(s)
        mw._quiet_updates = True
        assert "No release" in mw.check_updates(opener=_opener(code=404))
        assert "v9.9.9 is available" in mw.check_updates(opener=_opener({"tag_name": "v9.9.9"}))
        assert "up to date" in mw.check_updates(opener=_opener({"tag_name": "v" + __version__}))
        assert "Could not check" in mw.check_updates(opener=_opener(code=403))
        i18n.set_language("ar")
        try:
            dlg = mw.open_help()
            assert dlg.path.name == "USER_GUIDE.ar.md" and "PhraseExpress" in dlg.view.toPlainText()
            dlg.close()
        finally:
            i18n.set_language("en")
        mw.close()
    finally:
        s.close()


@pytest.fixture
def qtbot_free_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_release_setup_url_and_daily_check(monkeypatch, tmp_path):
    import io
    import json as _json
    from datetime import datetime, timedelta
    from phraseforge.app import PhraseForgeApp
    from phraseforge.db import Store
    data = {"tag_name": "v9.9.9", "html_url": "https://x/rel",
            "assets": [{"name": "B-PhraseForgeExpress-portable.exe", "browser_download_url": "p"},
                       {"name": "B-PhraseForgeExpress-Setup-9.9.9.exe", "browser_download_url": "https://x/setup.exe"}]}

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    rel = updates.latest_release(opener=lambda req, timeout: R(_json.dumps(data).encode()))
    assert rel["setup_url"] == "https://x/setup.exe" and rel["version"] == "9.9.9"
    assert updates.check_due("") and not updates.check_due(datetime.now().isoformat())
    assert updates.check_due((datetime.now() - timedelta(hours=25)).isoformat())

    store = Store(tmp_path / "u.db")
    shown = []

    class Fake:
        pass
    f = Fake()
    f.store = store
    f.poster = type("P", (), {"posted": type("S", (), {"emit": staticmethod(lambda fn: shown.append(fn))})()})()
    assert PhraseForgeApp.auto_check_updates(f, latest=lambda: rel)["version"] == "9.9.9"
    assert len(shown) == 1 and store.setting("updates.last_check")
    assert PhraseForgeApp.auto_check_updates(f, latest=lambda: rel, force=True) is None   # announced once
    assert PhraseForgeApp.auto_check_updates(f, latest=lambda: rel) is None              # not due yet
    store.set_setting("updates.auto_check", "0")
    store.set_setting("updates.notified_version", "")
    assert PhraseForgeApp.auto_check_updates(f, latest=lambda: rel, force=True) is None  # turned off
    store.close()
