"""Files attached to a phrase (G-21): a copy kept with PhraseForge, pasted as a file."""
import pytest

from phraseforge import paths
from phraseforge.importers import files


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()
    return tmp_path


def test_attach_keeps_a_copy_under_its_own_name(data):
    src = data / "Price list.pdf"
    src.write_bytes(b"%PDF-1.4 demo")
    macro = files.attach_file(src)
    assert macro.startswith('{#pastefile "attached/') and macro.endswith('/Price list.pdf"}')
    rel = macro[len('{#pastefile "'):-2]
    kept = files.resolve_attachment(rel)
    assert kept.name == "Price list.pdf" and kept.read_bytes() == b"%PDF-1.4 demo"
    src.unlink()                                          # the original may go away
    assert files.resolve_attachment(rel).is_file()
    assert files.attach_file(kept) == macro               # same content: same copy


def test_only_our_own_relative_paths_resolve(data):
    (data / "secret.txt").write_text("x")
    for bad in ("", "attached/../../secret.txt", "attached/nope/a.txt", str(data / "secret.txt"),
                "other/a.txt", "../secret.txt"):
        assert files.resolve_attachment(bad) is None


def test_too_large_and_missing_are_refused(data, monkeypatch):
    with pytest.raises(ValueError, match="Not a file"):
        files.attach_file(data / "none.bin")
    big = data / "big.bin"
    big.write_bytes(b"x" * 2048)
    monkeypatch.setattr(files, "MAX_ATTACHMENT", 1024 * 1024 // 1024)      # 1 KB for the test
    with pytest.raises(ValueError, match="larger"):
        files.attach_file(big)
