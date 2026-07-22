#!/usr/bin/env node
/**
 * Boltrig channel-gateway WhatsApp bridge (Baileys).
 *
 * Provenance (license obligation): DERIVED from the MIT-licensed Hermes agent
 * WhatsApp bridge (scripts/whatsapp-bridge/bridge.js, Copyright (c) 2025 Nous
 * Research, MIT license, https://github.com/NousResearch/hermes-agent). The
 * full MIT license text ships alongside this file in LICENSE.md.
 *
 * What was ADAPTED for Boltrig (decision 0003, condition 2 - the gateway owns
 * NO policy; who-may-talk is the kernel's binding/pairing rows):
 *   - STRIPPED: allowlist.js and every who-may-talk check (WHATSAPP_ALLOWED_USERS,
 *     matchesAllowedUser, the lid<->phone allowlist resolution), the
 *     self-chat/bot WHATSAPP_MODE policy, and the Hermes reply prefix (identity
 *     decoration, also policy). EVERY inbound human message is normalised and
 *     pushed; the kernel binding decides whether it becomes work.
 *   - STRIPPED: Hermes-specific extras - media download/cache dirs, the ffmpeg
 *     voice conversion, and the /edit, /send-media, /typing and /chat/:id
 *     endpoints. Media messages keep their caption (or a "[type received]"
 *     placeholder) as the text body.
 *   - CHANGED: inbound delivery is PUSH, not poll - each normalised event is
 *     POSTed to a configurable local endpoint (the whatsapp_adapter listener)
 *     instead of queued for GET /messages long-polling.
 *
 * What REMAINS (the reason a bridge process exists at all - condition 9 keeps
 * the Baileys SDK out of the Python image):
 *   - the Baileys session lifecycle: QR pairing (terminal), reconnect on drop,
 *     credential persistence under --session, a --pair-only mode for operators;
 *   - inbound message normalisation POSTed to the adapter;
 *   - the outbound POST /send endpoint;
 *   - loopback-only binding + Host-header validation (DNS-rebinding defence).
 *
 * Endpoints:
 *   POST /send    - send a text message { chatId, message } -> { success, messageId }
 *   GET  /health  - { status, uptime }
 *
 * Inbound push (per accepted message, POSTed to the adapter URL as JSON):
 *   { messageId, chatId, senderId, isGroup, body }
 *     messageId - Baileys message key.id (the platform's stable delivery id)
 *     chatId    - the chat JID (a phone JID for DMs, *@g.us for groups)
 *     senderId  - the sender JID (the group participant JID inside groups)
 *     isGroup   - boolean
 *     body      - text body (media caption or a "[type received]" placeholder)
 *
 * Echo/system filtering here is MECHANICS, not policy: our own fromMe echoes
 * (the bridge's own sends coming back), status broadcasts and empty/system
 * messages are dropped at debug so they can never loop or forge work.
 *
 * Usage:
 *   node bridge.js --port 3000 --session /data/whatsapp-session \
 *     --adapter-url http://127.0.0.1:3001/inbound
 *   node bridge.js --pair-only --session /data/whatsapp-session   # QR pair, then exit
 */

import { makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import express from 'express';
import { Boom } from '@hapi/boom';
import pino from 'pino';
import path from 'path';
import { mkdirSync } from 'fs';
import qrcode from 'qrcode-terminal';

// Parse CLI args
const args = process.argv.slice(2);
function getArg(name, defaultVal) {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : defaultVal;
}

const WHATSAPP_DEBUG =
  typeof process !== 'undefined' &&
  process.env &&
  typeof process.env.WHATSAPP_DEBUG === 'string' &&
  ['1', 'true', 'yes', 'on'].includes(process.env.WHATSAPP_DEBUG.toLowerCase());

const PORT = parseInt(getArg('port', '3000'), 10);
// Bind host: loopback by default (same-host adapter). Pass --host 0.0.0.0
// only inside a private container network where the gateway adapter is a
// sibling service - never on a shared interface (the /send endpoint has no
// auth beyond network position; the Host-header check below still applies,
// so pass the container alias in WA_ACCEPTED_HOSTS when you do this).
const HOST = getArg('host', '127.0.0.1');
const SESSION_DIR = getArg('session', process.env.WA_SESSION_DIR || path.join(process.cwd(), 'whatsapp-session'));
const ADAPTER_URL = getArg('adapter-url', process.env.ADAPTER_URL || 'http://127.0.0.1:3001/inbound');
const PAIR_ONLY = args.includes('--pair-only');
const MAX_MESSAGE_LENGTH = parseInt(process.env.WHATSAPP_MAX_MESSAGE_LENGTH || '4096', 10);
const CHUNK_DELAY_MS = parseInt(process.env.WHATSAPP_CHUNK_DELAY_MS || '300', 10);
// Per-call timeout for sock.sendMessage(): Baileys occasionally hangs on send;
// fail fast so the adapter sees a real delivery error and the outbox retries.
const SEND_TIMEOUT_MS = parseInt(process.env.WHATSAPP_SEND_TIMEOUT_MS || '60000', 10);

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function sendWithTimeout(chatId, payload, timeoutMs = SEND_TIMEOUT_MS) {
  let timer;
  const timeoutPromise = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`sendMessage timed out after ${timeoutMs / 1000}s`)),
      timeoutMs,
    );
  });
  return Promise.race([sock.sendMessage(chatId, payload), timeoutPromise])
    .finally(() => clearTimeout(timer));
}

function splitLongMessage(message, maxLength = MAX_MESSAGE_LENGTH) {
  const text = String(message || '');
  if (!text) return [];
  if (!Number.isFinite(maxLength) || maxLength < 1 || text.length <= maxLength) {
    return [text];
  }

  const chunks = [];
  let remaining = text;
  while (remaining.length > maxLength) {
    let splitAt = remaining.lastIndexOf('\n', maxLength);
    if (splitAt < Math.floor(maxLength / 2)) {
      splitAt = remaining.lastIndexOf(' ', maxLength);
    }
    if (splitAt < 1) splitAt = maxLength;

    chunks.push(remaining.slice(0, splitAt).trimEnd());
    remaining = remaining.slice(splitAt).trimStart();
  }
  if (remaining) chunks.push(remaining);
  return chunks;
}

// Unwrap the Baileys container messages (ephemeral / view-once / ...) to the
// concrete content node.
function getMessageContent(msg) {
  const content = msg?.message || {};
  if (content.ephemeralMessage?.message) return content.ephemeralMessage.message;
  if (content.viewOnceMessage?.message) return content.viewOnceMessage.message;
  if (content.viewOnceMessageV2?.message) return content.viewOnceMessageV2.message;
  if (content.documentWithCaptionMessage?.message) return content.documentWithCaptionMessage.message;
  return content;
}

// Text body only (media is NOT downloaded - the caption, or a placeholder,
// carries the signal; native media support is a documented follow-on).
function extractBody(messageContent) {
  if (messageContent.conversation) return messageContent.conversation;
  if (messageContent.extendedTextMessage?.text) return messageContent.extendedTextMessage.text;
  const media = [
    ['image', messageContent.imageMessage],
    ['video', messageContent.videoMessage],
    ['document', messageContent.documentMessage],
    ['audio', messageContent.audioMessage || messageContent.pttMessage],
  ];
  for (const [mediaType, node] of media) {
    if (node) return node.caption || `[${mediaType} received]`;
  }
  return '';
}

// Push one normalised event to the adapter. A failed push is dropped loud
// (logged): the bridge offers no bridge->adapter replay - the kernel's durable
// dedup on messageId covers replays of what DID arrive.
async function pushInbound(event) {
  try {
    const resp = await fetch(ADAPTER_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(event),
    });
    if (!resp.ok) {
      console.warn(`[bridge] adapter refused inbound ${event.messageId} (HTTP ${resp.status})`);
    }
  } catch (err) {
    console.warn(`[bridge] inbound push to adapter failed (${err.message}); message ${event.messageId} dropped`);
  }
}

mkdirSync(SESSION_DIR, { recursive: true });

const logger = pino({ level: 'warn' });

let sock = null;
let connectionState = 'disconnected';

async function startSocket() {
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false,
    browser: ['Boltrig Channel Gateway', 'Chrome', '120.0'],
    syncFullHistory: false,
    markOnlineOnConnect: false,
    // Required for Baileys 7.x: without this, incoming messages that need
    // E2EE session re-establishment are silently dropped (msg.message === null).
    getMessage: async (_key) => ({ conversation: '' }),
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log('\nScan this QR code with WhatsApp on your phone:\n');
      qrcode.generate(qr, { small: true });
      console.log('\nWaiting for scan...\n');
    }

    if (connection === 'close') {
      const reason = new Boom(lastDisconnect?.error)?.output?.statusCode;
      connectionState = 'disconnected';

      if (reason === DisconnectReason.loggedOut) {
        console.log('Logged out. Delete the session dir and restart to re-authenticate.');
        process.exit(1);
      } else {
        // 515 = restart requested (common after pairing). Always reconnect.
        if (reason === 515) {
          console.log('WhatsApp requested restart (code 515). Reconnecting...');
        } else {
          console.log(`Connection closed (reason: ${reason}). Reconnecting in 3s...`);
        }
        setTimeout(startSocket, reason === 515 ? 1000 : 3000);
      }
    } else if (connection === 'open') {
      connectionState = 'connected';
      console.log('WhatsApp connected.');
      if (PAIR_ONLY) {
        console.log('Pairing complete. Credentials saved.');
        // Give Baileys a moment to flush creds, then exit cleanly.
        setTimeout(() => process.exit(0), 2000);
      }
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify' && type !== 'append') return;

    for (const msg of messages) {
      if (!msg.message) continue;

      const chatId = msg.key.remoteJid;

      // Mechanics, not policy: never forward our own echoes or status/system
      // traffic - they can only loop or forge empty work.
      if (msg.key.fromMe) continue;
      if (!chatId || chatId === 'status@broadcast') {
        if (WHATSAPP_DEBUG) console.log(JSON.stringify({ event: 'ignored', reason: 'status_broadcast', chatId }));
        continue;
      }

      const body = extractBody(getMessageContent(msg));
      if (!body) {
        if (WHATSAPP_DEBUG) console.log(JSON.stringify({ event: 'ignored', reason: 'empty', chatId, messageKeys: Object.keys(msg.message || {}) }));
        continue;
      }

      const isGroup = chatId.endsWith('@g.us');
      await pushInbound({
        messageId: msg.key.id,
        chatId,
        senderId: msg.key.participant || chatId,
        isGroup,
        body,
      });
    }
  });
}

// HTTP server (loopback only - the adapter is a same-host peer).
const app = express();
app.use(express.json());

// Host-header validation - defends against DNS rebinding.
// The bridge binds loopback-only (127.0.0.1) but a victim browser on
// the same machine could be tricked into fetching from an attacker
// hostname that TTL-flips to 127.0.0.1. Reject any request whose Host
// header doesn't resolve to a loopback alias.
// See GHSA-ppp5-vxwm-4cf7.
// WA_ACCEPTED_HOSTS: comma-separated extra hostnames (e.g. the compose
// service alias) accepted in addition to the loopback aliases - needed when
// the bridge runs as a sibling container the adapter dials by service name.
const _ACCEPTED_HOST_VALUES = new Set([
  'localhost',
  '127.0.0.1',
  '[::1]',
  '::1',
  ...String(process.env.WA_ACCEPTED_HOSTS || '')
    .split(',')
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean),
]);

app.use((req, res, next) => {
  const raw = (req.headers.host || '').trim();
  if (!raw) {
    return res.status(400).json({ error: 'Missing Host header' });
  }
  // Strip port suffix: "localhost:3000" -> "localhost"
  const hostOnly = (raw.includes(':')
    ? raw.substring(0, raw.lastIndexOf(':'))
    : raw
  ).replace(/^\[|\]$/g, '').toLowerCase();
  if (!_ACCEPTED_HOST_VALUES.has(hostOnly)) {
    return res.status(400).json({
      error: 'Invalid Host header. Bridge accepts loopback hosts only.',
    });
  }
  next();
});

// Send a text message
app.post('/send', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Not connected to WhatsApp' });
  }

  const { chatId, message } = req.body;
  if (!chatId || !message) {
    return res.status(400).json({ error: 'chatId and message are required' });
  }

  try {
    const chunks = splitLongMessage(message);
    const messageIds = [];
    for (let i = 0; i < chunks.length; i += 1) {
      const sent = await sendWithTimeout(chatId, { text: chunks[i] });
      if (sent?.key?.id) messageIds.push(sent.key.id);
      if (chunks.length > 1 && i < chunks.length - 1) {
        await sleep(CHUNK_DELAY_MS);
      }
    }

    res.json({
      success: true,
      messageId: messageIds[messageIds.length - 1],
      messageIds,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Health check
app.get('/health', (req, res) => {
  res.json({
    status: connectionState,
    uptime: process.uptime(),
  });
});

// Start
if (PAIR_ONLY) {
  // Pair-only mode: just connect, show QR, save creds, exit. No HTTP server.
  console.log('WhatsApp pairing mode');
  console.log(`Session: ${SESSION_DIR}`);
  console.log();
  startSocket();
} else {
  app.listen(PORT, HOST, () => {
    console.log(`WhatsApp bridge listening on ${HOST}:${PORT}`);
    console.log(`Session stored in: ${SESSION_DIR}`);
    console.log(`Inbound pushes -> ${ADAPTER_URL}`);
    console.log('Policy note: who-may-talk is the kernel binding, not this bridge - every inbound message is forwarded.');
    console.log();
    startSocket();
  });
}
