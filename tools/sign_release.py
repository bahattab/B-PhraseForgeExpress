"""Sign release setup programs for PhraseForge's in-app update (FR-APP-05).

    python tools/sign_release.py --new-key           # once: prints a private and a public key
    PHRASEFORGE_RELEASE_KEY=<private> python tools/sign_release.py --version 0.7.0 dist/*Setup*.exe

Writes <file>.sig next to each file. Keep the private key secret (a repository secret named
RELEASE_SIGNING_KEY); put the public key in phraseforge/updates.py UPDATE_KEYS.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str]) -> int:
    from phraseforge import updates
    if argv[:1] == ["--new-key"]:
        from phraseforge.plugins.signing import new_key
        priv, pub = new_key()
        print(f"private (keep secret): {priv}\npublic (UPDATE_KEYS): {pub}")
        return 0
    version, files, required = "", [], False
    it = iter(argv)
    for a in it:
        if a == "--version":
            version = next(it, "")
        elif a == "--required":            # a release build: say loudly that it cannot self-update
            required = True
        elif a:
            files.append(a)
    key = os.environ.get("PHRASEFORGE_RELEASE_KEY", "").strip()
    if not key:
        print("PHRASEFORGE_RELEASE_KEY is not set: nothing signed", file=sys.stderr)
        if required:                       # a GitHub Actions warning on the release run
            print("::warning::This release is not signed, so PhraseForge cannot install it by itself. "
                  "Set the RELEASE_SIGNING_KEY secret (docs/releasing.md).")
        return 0
    if not version:
        print("--version is needed", file=sys.stderr)
        return 2
    for name in files:
        p = Path(name)
        p.with_name(p.name + updates.SIG_SUFFIX).write_bytes(updates.sign_file(p, key, version))
        print(f"signed {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
