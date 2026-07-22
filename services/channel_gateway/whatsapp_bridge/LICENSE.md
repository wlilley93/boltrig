# License and provenance

The files in this directory are DERIVED from the WhatsApp bridge of the
Hermes agent (`scripts/whatsapp-bridge/`), Copyright (c) 2025 Nous Research,
released under the MIT license
(<https://github.com/NousResearch/hermes-agent>).

Adaptation for Boltrig (decision 0003, condition 2): all who-may-talk policy
(`allowlist.js`, the `WHATSAPP_ALLOWED_USERS` allowlist, the self-chat/bot
`WHATSAPP_MODE` split, the Hermes reply prefix) was removed - in Boltrig that
decision belongs to the KERNEL's binding/pairing rows, never to the gateway.
What remains is transport: the Baileys session lifecycle, inbound message
normalisation pushed to the local adapter endpoint, and the outbound send
endpoint. See the header comment in `bridge.js` for the full change list.

`package-lock.json` is vendored verbatim from the source repo (root package
name/version adjusted to match the derived `package.json`) so the bridge
installs reproducibly (`npm ci`).

---

MIT License

Copyright (c) 2025 Nous Research

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
