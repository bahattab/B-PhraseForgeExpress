# Releasing and signed in-app updates

PhraseForge checks GitHub Releases for a newer version (Help > Check for updates, and once a
day unless switched off). It can also download and install the update itself, but only when
the setup is signed with a key built into PhraseForge (PRD FR-APP-05).

## One-time set-up of the release key

1. Make a key pair on your own PC:

       python tools/sign_release.py --new-key

2. Add the **private** key as a repository secret named `RELEASE_SIGNING_KEY`
   (GitHub > Settings > Secrets and variables > Actions). Never commit it.
3. Put the **public** key in `phraseforge/updates.py`:

       UPDATE_KEYS: frozenset[str] = frozenset({"<public key>"})

   and release that version. Versions released before this step can only open the download
   page; from the next version on, PhraseForge can update itself.

## What happens on a release

- The Windows build signs `B-PhraseForgeExpress-Setup-<version>.exe` and publishes
  `...Setup-<version>.exe.sig` next to it. The signature covers the file's SHA-256, its name
  and its version, so an older signed setup cannot be offered as a newer version. Without the
  secret the step signs nothing, the build still passes, and a release run shows a warning.
- PhraseForge downloads the `.sig` (at most 64 KB) and the setup (at most 400 MB), only from
  this project's releases on github.com. It checks the key is one of `UPDATE_KEYS` (never a key
  from the download), the Ed25519 signature, that the signed version is the offered one and
  newer than the running PhraseForge, and checks once more right before the setup starts.
  Redirects are followed only over https to GitHub's download hosts. A file that fails is
  deleted, and so is the download folder when nothing is installed.
- Only after the check, PhraseForge asks "Close PhraseForge and run the setup now?". Nothing
  installs without that click.

## Changing the key

Add the new public key to `UPDATE_KEYS` next to the old one, release, then switch the secret.
Remove the old key one release later.
