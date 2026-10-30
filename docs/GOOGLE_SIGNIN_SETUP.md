# Built-in "Sign in with Google" client (maintainer setup)

PhraseForge talks to the Google Drive API only with an OAuth client registered in Google Cloud.
Release builds can carry one built-in client, so users only click **Sign in with Google**. Without
it, the button opens a window that asks each user to create their own client (Client ID and secret).

The release workflow (`.github/workflows/windows-build.yml`, step "Built-in Google sign-in client")
writes the client into the build from two repository secrets. When they are missing, the step does
nothing and the build has no built-in client. That was the case for 0.5.4 to 0.5.6.

Other Drive-sync tools work the same way: those that need no user setup ship a client their
developer registered (bundled in the app, or kept behind a token server).

## One-time setup (about 10 minutes)

1. Open <https://console.cloud.google.com/> with the Google account that should own the app, and
   create a project (for example "PhraseForge").
2. **APIs & Services > Library:** enable **Google Drive API**.
3. **Google Auth Platform (OAuth consent screen):** user type **External**; app name "PhraseForge";
   support and developer e-mail. Scopes: PhraseForge asks only for `drive.file` (files PhraseForge
   created), `openid` and the user's e-mail address.
4. **Publishing status:** while the app is in **Testing**, only the listed test users can sign in,
   and Google expires their sign-in after 7 days. Choose **Publish app** (In production) so any
   user can sign in and stays signed in. Google may show an "unverified app" notice until the app
   is verified; check what the console asks for the scopes above.
5. **Clients > Create client:** application type **Desktop app**, name "PhraseForge desktop".
   Copy the **Client ID** (ends in `.apps.googleusercontent.com`) and the **Client secret**.
6. GitHub: repository **Settings > Secrets and variables > Actions > New repository secret**:
   - `GOOGLE_CLIENT_ID` = the Client ID
   - `GOOGLE_CLIENT_SECRET` = the Client secret
7. Build a release (Actions > Windows build > Run workflow, `release_tag` e.g. `v0.5.7`). The step
   log then says "Built-in Google client written."

A Desktop app client secret is not confidential: Google's installed-app flow treats it as public,
and every copy of the program contains it. Users' sign-in tokens are stored per user, sealed with
Windows DPAPI.

## Without any Google sign-in

If Google Drive for desktop is installed, choose **A folder** in Settings > Backup & Sync and click
**Find Google Drive**. PhraseForge fills in `<My Drive>\PhraseForge`, and Drive for desktop uploads
the files. No OAuth client is involved.
