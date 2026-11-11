import json

from phraseforge import io_formats as io
from phraseforge.db import Store
from phraseforge.models import AutotextMode, Folder, OutputMode, Phrase, Trigger, TriggerKind


def _sample() -> Store:
    s = Store(":memory:")
    a = s.add_folder(Folder("Work", apps_include="outlook.exe"))
    b = s.add_folder(Folder("Mail", parent_id=a.id))
    s.add_phrase(Phrase("Sig", "Best regards\nBob", folder_id=b.id, tags=["mail"], output_mode=OutputMode.PASTE,
                        triggers=[Trigger(TriggerKind.AUTOTEXT, "sig#", mode=AutotextMode.IMMEDIATE),
                                  Trigger(TriggerKind.HOTKEY, "ctrl+alt+s")]))
    s.add_phrase(Phrase("Top", "top level, \"quoted\""))
    s.set_var("company", "ACME")
    s.set_excluded_apps(["keepass.exe"])
    return s


def test_json_roundtrip(tmp_path):
    src = _sample()
    p = tmp_path / "e.json"
    assert io.export_json(src, p) == 2
    dst = Store(":memory:")
    dst.add_folder(Folder("Existing"))      # ids differ from source -> remap exercised
    counts = io.import_json(dst, p)
    assert counts == {"folders": 2, "phrases": 2}
    sig = dst.find_phrase("Sig")
    assert io.folder_path(dst, sig.folder_id) == "Work/Mail"
    assert sig.output_mode == OutputMode.PASTE and sig.tags == ["mail"]
    assert [(t.kind, t.value, t.mode) for t in sig.triggers] == [
        (TriggerKind.AUTOTEXT, "sig#", AutotextMode.IMMEDIATE), (TriggerKind.HOTKEY, "ctrl+alt+s", AutotextMode.DELIMITER)]
    work = dst.get_folder(dst.get_folder(sig.folder_id).parent_id)
    assert work.apps_include == "outlook.exe"
    assert dst.get_var("company") == "ACME"
    assert "keepass.exe" in dst.excluded_apps()


def test_json_import_into_folder(tmp_path):
    src = _sample()
    p = tmp_path / "e.json"
    io.export_json(src, p)
    dst = Store(":memory:")
    root = dst.add_folder(Folder("Imported"))
    io.import_json(dst, p, into_folder_id=root.id)
    assert io.folder_path(dst, dst.find_phrase("Sig").folder_id) == "Imported/Work/Mail"
    assert dst.find_phrase("Top").folder_id == root.id


def test_json_rejects_foreign(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"format": "other"}))
    import pytest
    with pytest.raises(ValueError):
        io.import_json(Store(":memory:"), p)


def test_csv_roundtrip(tmp_path):
    src = _sample()
    p = tmp_path / "e.csv"
    assert io.export_csv(src, p) == 2
    dst = Store(":memory:")
    assert io.import_csv(dst, p) == 2
    sig = dst.find_phrase("Sig")
    assert sig.content == "Best regards\nBob"
    assert io.folder_path(dst, sig.folder_id) == "Work/Mail"
    assert {t.value for t in sig.triggers} == {"sig#", "ctrl+alt+s"}
    assert dst.find_phrase("Top").content == 'top level, "quoted"'


def test_csv_without_header(tmp_path):
    p = tmp_path / "n.csv"
    p.write_text("Hello,hh,Hello there\n", encoding="utf-8")
    dst = Store(":memory:")
    assert io.import_csv(dst, p) == 1
    ph = dst.find_phrase("Hello")
    assert ph.content == "Hello there" and ph.triggers[0].value == "hh"


def test_text_folder_roundtrip(tmp_path):
    src = _sample()
    src.add_phrase(Phrase("Sig", "duplicate name"))
    src.add_phrase(Phrase('bad:/name?', "x"))
    d = tmp_path / "out"
    assert io.export_text_folder(src, d) == 4
    assert (d / "Work" / "Mail" / "Sig.txt").read_text(encoding="utf-8") == "Best regards\nBob"
    dst = Store(":memory:")
    assert io.import_text_folder(dst, d) == 4
    sig = [p for p in dst.phrases() if p.content == "Best regards\nBob"][0]
    assert io.folder_path(dst, sig.folder_id) == "Work/Mail"


def test_backup_restore(tmp_path):
    dbp = tmp_path / "live.db"
    s = Store(dbp)
    s.add_phrase(Phrase("Keep", "v1"))
    b = io.backup(s, tmp_path / "bk")
    assert b.is_file() and io.list_backups(tmp_path / "bk") == [b]
    s.add_phrase(Phrase("Later", "v2"))
    s.close()
    io.restore(dbp, b)
    s2 = Store(dbp)
    assert [p.description for p in s2.phrases()] == ["Keep"]
    s2.close()


def test_dispatch_import_export_roundtrip(tmp_path):
    from phraseforge import io_formats
    from phraseforge.db import Store
    from phraseforge.models import Phrase, Trigger, TriggerKind
    s = Store(":memory:")
    s.add_phrase(Phrase("Hello", "Hi {#date}", triggers=[Trigger(TriggerKind.AUTOTEXT, "hh")]))
    for name in ("out.json", "out.csv"):
        io_formats.export_file(s, tmp_path / name)
        t = Store(":memory:")
        io_formats.import_file(t, tmp_path / name)
        assert t.search("Hello")[0].content == "Hi {#date}"


def test_json_export_carries_attached_files(tmp_path, monkeypatch):
    import base64
    from phraseforge import paths
    from phraseforge.importers import files as fl
    pc1, pc2 = tmp_path / "pc1", tmp_path / "pc2"
    pc1.mkdir(); pc2.mkdir()
    monkeypatch.setattr(paths, "data_dir", lambda: pc1)
    src = tmp_path / "Offer.pdf"
    src.write_bytes(b"%PDF offer")
    macro = fl.attach_file(src)
    s = Store(":memory:")
    s.add_phrase(Phrase("Offer", "Attached: " + macro))
    out = tmp_path / "e.json"
    io.export_json(s, out)
    d = json.loads(out.read_text(encoding="utf-8"))
    (item,) = d["attachments"].values()
    assert item["name"] == "Offer.pdf" and base64.b64decode(item["data"]) == b"%PDF offer"

    monkeypatch.setattr(paths, "data_dir", lambda: pc2)
    counts = io.import_json(Store(":memory:"), out)
    assert counts["attachments"] == 1
    kept = fl.resolve_attachment(macro[len('{#pastefile "'):-2])
    assert kept is not None and kept.read_bytes() == b"%PDF offer"


def test_import_drops_attachments_that_do_not_match(tmp_path, monkeypatch):
    import base64
    from phraseforge import paths
    from phraseforge.importers import files as fl
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    bad = {"format": "phraseforge", "phrases": [], "attachments": {
        "0123456789abcdef": {"name": "x.txt", "data": base64.b64encode(b"evil").decode()},
        "zz": {"name": "../../x", "data": "aGk="},
        "fedcba9876543210": {"name": "y", "data": "not base64!"}}}
    assert io.import_dict(Store(":memory:"), bad)["attachments"] == 0
    assert not (fl.assets_dir() / fl.ATTACHED).exists() or not any((fl.assets_dir() / fl.ATTACHED).rglob("*.txt"))
