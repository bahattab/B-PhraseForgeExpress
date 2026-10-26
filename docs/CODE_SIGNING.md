# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

> Status: the application to SignPath Foundation is pending. Until it is approved,
> releases are **not signed** and Windows SmartScreen may warn ("More info > Run anyway").

## What is signed

Only files built by GitHub Actions from this repository's source
(`.github/workflows/windows-build.yml`) are signed:

- `B-PhraseForgeExpress.exe` (inside the installer and the zip)
- `B-PhraseForgeExpress-portable.exe`
- `B-PhraseForgeExpress-Setup-<version>.exe`

Files built on a personal computer are never signed.

## Team roles

- Committers and reviewers: [repository members](https://github.com/bahattab/B-PhraseForgeExpress/graphs/contributors)
- Approvers: the repository owner ([bahattab](https://github.com/bahattab)) approves every signing request.

## Privacy

This program will not transfer any information to other networked systems unless
specifically requested by the user or the person installing or operating it.

The features that connect to the internet, all started or configured by the user, are:

- **Check for updates** (button): asks the GitHub releases API for the latest version.
- **Backup and sync with Google Drive**: only after the user signs in with Google.
- **AI text processing and translation**: only to the service and API key the user enters
  (OpenAI, Anthropic, OpenRouter, DeepL, or a local Ollama/GPT4All).
- **Phrase macros** that open web pages or send web requests, when a phrase the user wrote uses them.

## Setting up signing (maintainer)

1. Apply at <https://signpath.org/apply.html>. Link this page as the code signing policy.
2. After approval, in SignPath create two artifact configurations with the slugs `exe` and
   `setup`, using `packaging/signpath/exe.xml` and `packaging/signpath/setup.xml`.
   Create a signing policy (default slug `release-signing`) and connect GitHub as a trusted build system.
3. In GitHub: **Settings > Secrets and variables > Actions**
   - Secret `SIGNPATH_API_TOKEN`: a SignPath API token for a CI user that can submit requests.
   - Variable `SIGNPATH_ORGANIZATION_ID`: your SignPath organization ID.
   - Optional variables `SIGNPATH_PROJECT_SLUG` (default `B-PhraseForgeExpress`) and
     `SIGNPATH_POLICY_SLUG` (default `release-signing`).
4. The next build on `main` (or a manual run with `release_tag`) signs the files. The build
   checks each file with `Get-AuthenticodeSignature` and fails if the signature is not valid.
   Pull-request builds are never signed.
