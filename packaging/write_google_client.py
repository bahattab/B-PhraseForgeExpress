"""Write the built-in Google sign-in client (phraseforge/cloud/google_client.json) for a build.

Reads GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (GitHub repository secrets in the release
workflow). Without them nothing is written and users set up their own client in
Settings > Backup & Sync. The file is git-ignored and never committed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    out = ROOT / "phraseforge" / "cloud" / "google_client.json"
    if not (cid and secret):
        print("No GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET: building without a built-in Google client.")
        return 0
    if not cid.endswith(".apps.googleusercontent.com"):
        print("GOOGLE_CLIENT_ID does not look like a Google OAuth client ID.", file=sys.stderr)
        return 1
    from phraseforge.cloud.gdrive import client_json
    out.write_text(json.dumps(client_json(cid, secret), indent=2), encoding="utf-8")
    print(f"Built-in Google client written ({cid[:12]}...).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
