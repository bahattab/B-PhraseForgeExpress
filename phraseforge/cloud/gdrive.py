"""Google Drive access with the user's own Google account.

Sign-in uses Google's OAuth "installed app" flow: the default browser opens
Google's login page, the user approves, and Google redirects to a temporary
localhost port. PhraseForge never sees the password.

Scope: drive.file only, so PhraseForge can see and change only the files and
folders it created itself, nothing else in the user's Drive.

Google requires an OAuth client ID (a "Desktop app" client from a Google Cloud
project). PhraseForge looks for one in this order:
1. the user's own client (JSON file or pasted ID + secret, Settings > Backup & Sync),
   kept in the data folder;
2. the client built into the program (phraseforge/cloud/google_client.json, written
   by the release build from the GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET secrets).
For a "Desktop app" client Google does not treat the secret as confidential, so a
built-in client is the normal way installed apps sign in.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from phraseforge import paths
from phraseforge.cloud.secure import protect, unprotect

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]
FOLDER_MIME = "application/vnd.google-apps.folder"


class GDriveError(RuntimeError):
    pass


def client_file() -> Path:
    return paths.data_dir() / "google_oauth_client.json"


def token_file() -> Path:
    return paths.data_dir() / "google_token.bin"


def builtin_client_file() -> Path:
    """OAuth client shipped with the program (absent in source checkouts without one)."""
    return Path(__file__).with_name("google_client.json")


def _valid_installed(data) -> bool:
    inst = data.get("installed") if isinstance(data, dict) else None
    return isinstance(inst, dict) and bool(inst.get("client_id")) and bool(inst.get("client_secret"))


def client_config() -> dict | None:
    """The OAuth client to sign in with: the user's own first, then the built-in one."""
    for f in (client_file(), builtin_client_file()):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _valid_installed(data):
            return data
    return None


def client_source() -> str:
    """"own", "builtin" or "" (no client)."""
    cfg = client_config()
    if cfg is None:
        return ""
    try:
        own = json.loads(client_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        own = None
    return "own" if own == cfg else "builtin"


def client_json(client_id: str, client_secret: str) -> dict:
    return {"installed": {
        "client_id": client_id.strip(), "client_secret": client_secret.strip(),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": ["http://localhost"]}}


def install_client_values(client_id: str, client_secret: str) -> None:
    """Save a pasted Client ID and secret as the user's own OAuth client."""
    cid, sec = (client_id or "").strip(), (client_secret or "").strip()
    if not cid.endswith(".apps.googleusercontent.com"):
        raise GDriveError('The Client ID ends with ".apps.googleusercontent.com". Copy it from Google Cloud '
                          'Console > Credentials > your "Desktop app" OAuth client.')
    if not sec:
        raise GDriveError("Paste the client secret too (shown next to the Client ID).")
    client_file().parent.mkdir(parents=True, exist_ok=True)
    client_file().write_text(json.dumps(client_json(cid, sec), indent=2), encoding="utf-8")


def install_client_file(src: str | Path) -> None:
    """Validate and copy a downloaded OAuth client JSON into the data folder."""
    try:
        data = json.loads(Path(src).read_text(encoding="utf-8"))
    except ValueError as e:
        raise GDriveError(f"This file is not an OAuth client JSON file: {e}") from e
    if not _valid_installed(data):
        raise GDriveError('This is not a "Desktop app" OAuth client file. In Google Cloud Console create '
                          'Credentials > OAuth client ID > Application type "Desktop app" and download its JSON.')
    client_file().parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, client_file())


def remove_own_client() -> None:
    client_file().unlink(missing_ok=True)


class GoogleDrive:
    def __init__(self):
        self._creds = None
        self._service = None

    # ------------------------------------------------------------ account
    def has_client(self) -> bool:
        return client_config() is not None

    def signed_in(self) -> bool:
        return self._load_creds() is not None

    def sign_in(self, timeout_s: int = 300):
        """Open the browser for Google login. Blocks until done (run off the UI thread)."""
        cfg = client_config()
        if cfg is None:
            raise GDriveError("Set up the Google OAuth client first (Settings > Backup & Sync).")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
        creds = flow.run_local_server(
            host="localhost", port=0, open_browser=True, timeout_seconds=timeout_s,
            authorization_prompt_message="", prompt="consent", access_type="offline",
            success_message="PhraseForge is now connected to Google Drive. You can close this tab.")
        if creds is None:
            raise GDriveError("Google sign-in was not completed.")
        self._save_creds(creds)
        self._creds, self._service = creds, None
        return creds

    def sign_out(self) -> None:
        creds = self._load_creds()
        if creds is not None:
            try:  # revoke at Google so the token can't be used anywhere
                import requests
                requests.post("https://oauth2.googleapis.com/revoke",
                              params={"token": creds.refresh_token or creds.token}, timeout=10)
            except Exception:
                pass
        token_file().unlink(missing_ok=True)
        self._creds = self._service = None

    def email(self) -> str:
        try:
            about = self.service().about().get(fields="user(emailAddress)").execute()
            return about.get("user", {}).get("emailAddress", "")
        except Exception:
            return ""

    def _save_creds(self, creds) -> None:
        token_file().write_bytes(protect(creds.to_json().encode("utf-8")))

    def _load_creds(self):
        if self._creds is not None:
            return self._creds
        f = token_file()
        if not f.is_file():
            return None
        try:
            from google.oauth2.credentials import Credentials
            info = json.loads(unprotect(f.read_bytes()).decode("utf-8"))
            creds = Credentials.from_authorized_user_info(info, SCOPES)
        except Exception:
            return None
        if not creds.valid and creds.refresh_token:
            try:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                self._save_creds(creds)
            except Exception:
                return None
        self._creds = creds
        return creds

    def service(self):
        if self._service is None:
            creds = self._load_creds()
            if creds is None:
                raise GDriveError("Not signed in to Google Drive.")
            from googleapiclient.discovery import build
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    # ------------------------------------------------------------ files
    def ensure_folder(self, name: str) -> str:
        """Find (or create) a top-level folder that PhraseForge created."""
        q = (f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and mimeType = '{FOLDER_MIME}' "
             "and trashed = false and 'root' in parents")
        res = self.service().files().list(q=q, spaces="drive", fields="files(id,name)").execute()
        if res.get("files"):
            return res["files"][0]["id"]
        meta = {"name": name, "mimeType": FOLDER_MIME, "parents": ["root"]}
        return self.service().files().create(body=meta, fields="id").execute()["id"]

    def list(self, folder_id: str) -> list[dict]:
        out, token = [], None
        while True:
            res = self.service().files().list(
                q=f"'{folder_id}' in parents and trashed = false", spaces="drive", pageToken=token,
                fields="nextPageToken, files(id,name,modifiedTime,size,appProperties)").execute()
            out += res.get("files", [])
            token = res.get("nextPageToken")
            if not token:
                return out

    def upload(self, local: str | Path, name: str, folder_id: str, props: dict | None = None,
               file_id: str | None = None) -> str:
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(str(local), mimetype="application/octet-stream", resumable=True)
        body = {"name": name, "appProperties": {k: str(v) for k, v in (props or {}).items()}}
        files = self.service().files()
        if file_id:
            return files.update(fileId=file_id, body=body, media_body=media, fields="id").execute()["id"]
        body["parents"] = [folder_id]
        return files.create(body=body, media_body=media, fields="id").execute()["id"]

    def download(self, file_id: str, dest: str | Path) -> None:
        from googleapiclient.http import MediaIoBaseDownload
        req = self.service().files().get_media(fileId=file_id)
        with open(dest, "wb") as fh:
            dl = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = dl.next_chunk()

    def delete(self, file_id: str) -> None:
        self.service().files().delete(fileId=file_id).execute()
