# Third-party notices

PhraseForge is MIT licensed (see LICENSE). It includes the following third-party material.

## PromptBoost (prompt text)

The "Boost prompt" instruction in `phraseforge/ai.py` (`BOOST_INSTRUCTION`) is taken from the
PromptBoost VS Code extension, <https://github.com/chrisdias/vscode-promptboost>, with one line
added by PhraseForge (keep the prompt's language and `{#macros}`).

```
MIT License

Copyright (c) 2025 Chris Dias

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Prompt Tower (behaviour only)

The Prompt Tower window rebuilds the workflow of <https://github.com/backnotprop/prompt-tower>
(AGPL-3.0). No code or text from it is included; see `docs/PROMPT_TOWER_SPEC.md`.

## AI Prompt Optimizer (templates)

The "API endpoint" and "Database model" templates in `phraseforge/prompt_optimizer.py` come from
<https://github.com/mhemdan/ai-prompt-optimizer> (`src/config/templates.json`), MIT License,
Copyright (c) 2025 Mohamed Hemdan (same MIT terms as above). The system prompt is PhraseForge's
own; it keeps that extension's "Optimized Prompt:" marker.

## Mistral OCR Unofficial (behaviour)

`phraseforge/mistral_ocr.py` follows the workflow of <https://github.com/sldyns/mistral-ocr-unofficial>
(MIT, Copyright (c) 2025 sldyns): results saved in a folder named after the file, Markdown plus
images. PhraseForge calls Mistral's documented REST endpoint directly instead of running that
extension's Python script.
