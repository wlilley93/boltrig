# Third-party notices

## OpenWorker

Portions of the Boltrig Worker presentation are derived from OpenWorker commit
`f96ad4c8e6865f0aec519681a3717b6bcdd81546`.

MIT License

Copyright (c) 2024 Andrew Ng

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Pocket TTS, and the voices it ships with

The self-hosted voice runtime uses Kyutai's Pocket TTS model
(`kyutai/pocket-tts`), released under **CC-BY-4.0**.

Boltrig's default character, Familiar, speaks with the catalogue voice `vera`,
which derives from the **CSTR VCTK Corpus** (`vctk/p229_023_enhanced.wav`),
released under **CC-BY-4.0** by the Centre for Speech Technology Research,
University of Edinburgh.

Both licences require attribution, which this section provides.

**The catalogue is licensed per source dataset, not uniformly.** Anyone changing
the shipped default, or offering catalogue voices in a build that is distributed,
must check the source of each voice they ship:

| source | licence | distributable |
| --- | --- | --- |
| voice-donations, Voice-Zero, Mozilla Common Voice | CC0 | yes, no attribution required |
| VCTK, CML-TTS, Alba MacKenna | CC-BY-4.0 | yes, with attribution |
| **Expresso, EARS** | **CC-BY-NC-4.0** | **no — non-commercial only** |

At the time of writing that makes `cosette` (Expresso) and `jean` (EARS)
undistributable in a commercial build, while the other twenty catalogue voices
are fine. A voice's source is resolvable from
`pocket_tts.utils.utils._ORIGINS_OF_PREDEFINED_VOICES`, which maps each name to
the dataset path it came from — that mapping is the authority, not the voice's
name.

Kyutai's usage policy additionally prohibits voice impersonation or cloning
without explicit and lawful consent. Locally cloned voices are never shipped:
`voices/*.safetensors` are private by rule, because a clone is a specific
person's voice.
