"""PhraseExpress text exports: one .txt per phrase, or a folder tree ("Files including directory structure")."""
from phraseforge import io_formats
from phraseforge.db import Store
from phraseforge.importers import phraseexpress as pe


def _store(tmp_path):
    return Store(tmp_path / "t.db")


def test_single_txt_is_one_phrase_named_after_the_file(tmp_path):
    s = _store(tmp_path)
    f = tmp_path / "00 - Agents.txt"
    f.write_text("00 - Agents\n", encoding="utf-8")
    rep = pe.import_any(s, f)
    assert rep.imported == 1
    ph = s.phrases()[0]
    assert ph.description == "00 - Agents" and ph.content.strip() == "00 - Agents"
    assert s.get_folder(ph.folder_id).name == pe.PE_FOLDER
    s.close()


def test_several_txt_files_share_one_folder_and_read_utf16_arabic(tmp_path):
    s = _store(tmp_path)
    a = tmp_path / "تحية.txt"
    a.write_bytes("مرحبًا بك".encode("utf-16"))
    b = tmp_path / "Sign.txt"
    b.write_text("Kind regards", encoding="utf-8-sig")
    rep = pe.import_text_files(s, [a, b])
    assert rep.imported == 2
    got = {p.description: p.content for p in s.phrases()}
    assert got == {"تحية": "مرحبًا بك", "Sign": "Kind regards"}
    assert len({p.folder_id for p in s.phrases()}) == 1
    pe.import_text_files(s, [b])                  # second import reuses the folder
    assert [f.name for f in s.folders(None)].count(pe.PE_FOLDER) == 1
    s.close()


def test_tabular_txt_is_still_read_as_a_table(tmp_path):
    s = _store(tmp_path)
    f = tmp_path / "export.txt"
    f.write_text("Description\tContent\nHi\tHello there\nBye\tSee you\n", encoding="utf-8")
    assert pe.looks_like_table(f.read_text(encoding="utf-8"))
    assert pe.import_any(s, f).imported == 2
    s.close()


def test_directory_structure_export(tmp_path):
    s = _store(tmp_path)
    root = tmp_path / "My Phrases"
    (root / "Agents" / "Sub").mkdir(parents=True)
    (root / "Agents" / "00 - Agents.txt").write_text("00 - Agents", encoding="utf-8")
    (root / "Agents" / "Sub" / "Deep.txt").write_text("deep text", encoding="utf-8")
    rep = pe.import_any(s, root)
    assert rep.imported == 2
    deep = [p for p in s.phrases() if p.description == "Deep"][0]
    assert io_formats.folder_path(s, deep.folder_id) == "My Phrases/Agents/Sub"
    s.close()


def test_file_import_of_one_txt_does_not_import_its_whole_folder(tmp_path):
    s = _store(tmp_path)
    (tmp_path / "other.txt").write_text("not me", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deeper.txt").write_text("nor me", encoding="utf-8")
    f = tmp_path / "mine.txt"
    f.write_text("only me", encoding="utf-8")
    assert io_formats.import_file(s, f) == 1
    assert [p.content for p in s.phrases()] == ["only me"]
    s.close()


def test_windows_line_ends_become_newlines(tmp_path):
    f = tmp_path / "crlf.txt"
    f.write_bytes("a\r\nb\rc".encode("utf-16"))
    assert io_formats.read_text_any(f) == "a\nb\nc"
