# Prompt Tower in PhraseForge: behaviour spec and clean-room notes

PhraseForge's **Prompt Tower** (Tools > AI > Prompt Tower, tray menu, `{#prompttower}` macro)
rebuilds the workflow of the Prompt Tower VS Code extension
(<https://github.com/backnotprop/prompt-tower>, checked 2026-10-28) as part of a Windows desktop
text expander.

## Method

The work followed the reverse-engineering approach of
[REA](https://github.com/morluto/rea) and [LeanREA](https://github.com/aicodeking/leanrea): look at
the target with ordinary tools first, write down observable behaviour, then rebuild. The target
here is open source, so the "recon" was reading its public README, its `package.json` settings
schema (`contributes.configuration`) and the names of its UI controls and services.

**No code was copied.** The extension is licensed **AGPL-3.0**; PhraseForge is **MIT**. Only
behaviour, setting names and output conventions (facts that are not copyrightable expression)
were used. The Python in `phraseforge/prompttower.py` and `phraseforge/ui/prompt_tower.py` was
written for PhraseForge from this spec.

## Observed behaviour of the original (source: README and settings schema)

| Area | Original | PhraseForge |
| --- | --- | --- |
| File selection | Checkbox tree of the VS Code workspace | Checkbox tree of any folder (Browse, recent folders), folders tri-state, filter box |
| Ignore rules | Built-in always-ignore list, `.gitignore` (`promptTower.useGitignore`), `.towerignore` | Same three sources, plus an extra list in the `prompttower.ignore` setting. Only the root `.gitignore` is read |
| File block | `blockTemplate` with `{fileNameWithExtension}` `{rawFilePath}` `{fileName}` `{fileExtension}` `{fullPath}` `{fileContent}`; default `<file name="…" path="…">…</file>` | Same placeholders and default; Markdown preset; Custom format editor |
| Between blocks | `blockSeparator` (`\n`), `blockTrimLines` | Same |
| Project tree | `projectTreeFormat`: enabled, type `fullFilesAndDirectories` / `fullDirectoriesOnly` / `selectedFilesOnly`, `showFileSize`, template with `{projectTree}` | Whole tree / folders only / selected files only / no tree; sizes; same template |
| Wrapper | `wrapperFormat.template` with `{treeBlock}` `{blocks}` `{timestamp}` `{fileCount}` `{workspaceRoot}` (`null` = off) | Same placeholders; empty = off |
| Prefix / suffix | Text areas before and after the context, with history | Same, history of the last 20 texts each |
| Tokens | Live count (gpt-tokenizer) | Live **estimate** (about 4 characters per token for Latin text and code, 2 for Arabic). No tokenizer is bundled, so it is labelled "about" |
| Large files | Warning above `maxFileSizeWarningKB` (500) | Asks before adding a file above 500 KB |
| Remove comments | Option | Option for C-style, `#`, HTML and SQL comments (strings kept) |
| Output | Copy to clipboard, preview, send to editor | Copy, preview, **save as a PhraseForge phrase** |
| Push to AI site | Opens ChatGPT / Claude / Gemini / AI Studio and pastes with OS automation | Copies the prompt and opens the site; the user pastes with Ctrl+V (no simulated keystrokes into a browser) |
| Templates | (prefix/suffix history) | **Saved prompts**: folder + files + texts + format, reloadable, and insertable anywhere with `{#prompttower "name"}` (built from the files as they are at that moment) |
| GitHub issues / PR diffs | Imports with a GitHub token | **Not included** (needs a GitHub token and network access; may come later) |

## Differences and limits

- Token numbers are estimates, not exact counts.
- Nested `.gitignore` files inside sub-folders are not read.
- Binary files (containing a NUL byte in the first 4 KB) are skipped and listed after copying.
- The scan stops at 20,000 entries to keep the window responsive on huge folders.
