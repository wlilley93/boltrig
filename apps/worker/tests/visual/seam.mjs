// A PNG reader and a seam probe.
//
// WHY A DECODER RATHER THAN A LIBRARY. apps/worker's package.json is public
// graph and this is test tooling; a dependency added for a 60-line decode would
// travel to every consumer of the package. Playwright only ever hands back an
// encoded PNG, so decoding is the price of measuring a composited page at all.
//
// WHY MEASURE THE COMPOSITED PAGE. A body's own frame can be measured offscreen
// (render-bodies.mjs), and the host's colour can be read from computed style,
// but a SEAM is neither: it is the step between them, and it only exists once
// the browser has put one on top of the other.

import { inflateSync } from "node:zlib";

const CHANNELS = { 0: 1, 2: 3, 4: 2, 6: 4 };

/** Decode an 8-bit PNG to { width, height, channels, data }. */
export function decodePng(buffer) {
  if (buffer.readUInt32BE(0) !== 0x89504e47) throw new Error("not a PNG");
  let offset = 8;
  let header = null;
  const parts = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString("ascii", offset + 4, offset + 8);
    const body = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      header = {
        width: body.readUInt32BE(0),
        height: body.readUInt32BE(4),
        depth: body[8],
        colour: body[9],
        interlace: body[12],
      };
    } else if (type === "IDAT") {
      parts.push(body);
    } else if (type === "IEND") {
      break;
    }
    offset += 12 + length;
  }
  if (!header) throw new Error("PNG has no IHDR");
  if (header.depth !== 8) throw new Error(`unsupported bit depth ${header.depth}`);
  if (header.interlace !== 0) throw new Error("interlaced PNG is not supported");
  const channels = CHANNELS[header.colour];
  if (!channels) throw new Error(`unsupported colour type ${header.colour}`);

  const raw = inflateSync(Buffer.concat(parts));
  const stride = header.width * channels;
  const data = Buffer.alloc(stride * header.height);
  let read = 0;
  for (let y = 0; y < header.height; y++) {
    const filter = raw[read++];
    const line = data.subarray(y * stride, (y + 1) * stride);
    raw.copy(line, 0, read, read + stride);
    read += stride;
    const prior = y > 0 ? data.subarray((y - 1) * stride, y * stride) : null;
    unfilter(filter, line, prior, channels, stride);
  }
  return { width: header.width, height: header.height, channels, data };
}

function unfilter(filter, line, prior, channels, stride) {
  const left = (i) => (i >= channels ? line[i - channels] : 0);
  const up = (i) => (prior ? prior[i] : 0);
  const upLeft = (i) => (prior && i >= channels ? prior[i - channels] : 0);
  switch (filter) {
    case 0: return;
    case 1:
      for (let i = channels; i < stride; i++) line[i] = (line[i] + left(i)) & 255;
      return;
    case 2:
      for (let i = 0; i < stride; i++) line[i] = (line[i] + up(i)) & 255;
      return;
    case 3:
      for (let i = 0; i < stride; i++) line[i] = (line[i] + ((left(i) + up(i)) >> 1)) & 255;
      return;
    case 4:
      for (let i = 0; i < stride; i++) line[i] = (line[i] + paeth(left(i), up(i), upLeft(i))) & 255;
      return;
    default: throw new Error(`unknown PNG filter ${filter}`);
  }
}

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

/** Mean RGB of an axis-aligned box, clamped to the image. */
export function meanOf(image, x0, y0, x1, y1) {
  const { width, height, channels, data } = image;
  const left = Math.max(0, Math.floor(x0));
  const top = Math.max(0, Math.floor(y0));
  const right = Math.min(width, Math.ceil(x1));
  const bottom = Math.min(height, Math.ceil(y1));
  let r = 0;
  let g = 0;
  let b = 0;
  let n = 0;
  for (let y = top; y < bottom; y++) {
    for (let x = left; x < right; x++) {
      const i = (y * width + x) * channels;
      r += data[i];
      g += data[i + 1];
      b += data[i + 2];
      n += 1;
    }
  }
  if (n === 0) return null;
  return [r / n, g / n, b / n];
}

/**
 * The step across each of the card's four edges, in 0-255 units.
 *
 * A band is taken just inside and just outside each edge, skipping `skip`
 * pixels either side of the boundary so antialiasing of the boundary itself is
 * not measured as a step. The reported number is the largest per-channel
 * difference, because a seam that is only in the blue channel is still a seam.
 */
export function seamAcross(image, box, { band = 6, skip = 2 } = {}) {
  const edges = {
    top: [
      [box.x + band, box.y - skip - band, box.x + box.width - band, box.y - skip],
      [box.x + band, box.y + skip, box.x + box.width - band, box.y + skip + band],
    ],
    bottom: [
      [box.x + band, box.y + box.height + skip, box.x + box.width - band,
        box.y + box.height + skip + band],
      [box.x + band, box.y + box.height - skip - band, box.x + box.width - band,
        box.y + box.height - skip],
    ],
    left: [
      [box.x - skip - band, box.y + band, box.x - skip, box.y + box.height - band],
      [box.x + skip, box.y + band, box.x + skip + band, box.y + box.height - band],
    ],
    right: [
      [box.x + box.width + skip, box.y + band, box.x + box.width + skip + band,
        box.y + box.height - band],
      [box.x + box.width - skip - band, box.y + band, box.x + box.width - skip,
        box.y + box.height - band],
    ],
  };
  const out = {};
  for (const [name, [outsideBox, insideBox]] of Object.entries(edges)) {
    const outside = meanOf(image, ...outsideBox);
    const inside = meanOf(image, ...insideBox);
    out[name] = outside && inside
      ? {
        outside: outside.map(round1),
        inside: inside.map(round1),
        step: round1(Math.max(...outside.map((value, i) => Math.abs(value - inside[i])))),
      }
      : null;
  }
  out.worst = round1(Math.max(...Object.values(out).map((edge) => edge?.step ?? 0)));
  return out;
}

const round1 = (value) => Math.round(value * 10) / 10;
