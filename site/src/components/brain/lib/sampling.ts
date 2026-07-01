import { Object3D, Vector3 } from "three";

/**
 * Geometry helpers for the particle brain — flatten a loaded model's meshes
 * into a triangle soup, then uniformly sample points across that surface.
 * Ported verbatim (in behaviour) from `scenes/brain-particles.html`.
 */

/** Convert a `#rrggbb` hex string to a normalised RGB vector (no gamma). */
export function hexToVec3(hex: string): Vector3 {
  const n = parseInt(hex.slice(1), 16);
  return new Vector3(
    ((n >> 16) & 255) / 255,
    ((n >> 8) & 255) / 255,
    (n & 255) / 255,
  );
}

/**
 * Flatten every mesh under `root` into world-space triangles, stored as a flat
 * Float32Array of 9 floats per triangle: [ax,ay,az, bx,by,bz, cx,cy,cz].
 */
export function gatherTriangles(root: Object3D): Float32Array {
  const tris: number[] = [];
  const tmpA = new Vector3();
  const tmpB = new Vector3();
  const tmpC = new Vector3();
  root.updateMatrixWorld(true);
  root.traverse((node) => {
    const mesh = node as Object3D & {
      isMesh?: boolean;
      geometry?: import("three").BufferGeometry;
    };
    if (!mesh.isMesh || !mesh.geometry) return;
    const geom = mesh.geometry;
    const pos = geom.attributes.position;
    const idx = geom.index;
    const mat = mesh.matrixWorld;
    if (idx) {
      for (let i = 0; i < idx.count; i += 3) {
        const a = idx.array[i];
        const b = idx.array[i + 1];
        const c = idx.array[i + 2];
        tmpA.fromBufferAttribute(pos, a).applyMatrix4(mat);
        tmpB.fromBufferAttribute(pos, b).applyMatrix4(mat);
        tmpC.fromBufferAttribute(pos, c).applyMatrix4(mat);
        tris.push(
          tmpA.x, tmpA.y, tmpA.z,
          tmpB.x, tmpB.y, tmpB.z,
          tmpC.x, tmpC.y, tmpC.z,
        );
      }
    } else {
      for (let i = 0; i < pos.count; i += 3) {
        tmpA.fromBufferAttribute(pos, i).applyMatrix4(mat);
        tmpB.fromBufferAttribute(pos, i + 1).applyMatrix4(mat);
        tmpC.fromBufferAttribute(pos, i + 2).applyMatrix4(mat);
        tris.push(
          tmpA.x, tmpA.y, tmpA.z,
          tmpB.x, tmpB.y, tmpB.z,
          tmpC.x, tmpC.y, tmpC.z,
        );
      }
    }
  });
  return Float32Array.from(tris);
}

/**
 * Sample `count` points across the triangle soup, weighted by triangle area.
 * Returns the point positions and the geometric surface normal at each point
 * (the source triangle's normal) — used to keep the live "flow" motion tangent
 * to the brain's surface.
 */
export function sampleSurface(
  triArray: Float32Array,
  count: number,
): { positions: Float32Array; normals: Float32Array } {
  const nTris = triArray.length / 9;
  const areas = new Float32Array(nTris);
  let total = 0;
  const ax = new Vector3();
  const bx = new Vector3();
  const cx = new Vector3();
  for (let i = 0; i < nTris; i++) {
    const o = i * 9;
    ax.set(triArray[o], triArray[o + 1], triArray[o + 2]);
    bx.set(triArray[o + 3], triArray[o + 4], triArray[o + 5]);
    cx.set(triArray[o + 6], triArray[o + 7], triArray[o + 8]);
    bx.sub(ax);
    cx.sub(ax);
    const area = bx.cross(cx).length() * 0.5;
    areas[i] = area;
    total += area;
  }
  const cdf = new Float32Array(nTris);
  let acc = 0;
  for (let i = 0; i < nTris; i++) {
    acc += areas[i] / total;
    cdf[i] = acc;
  }
  const out = new Float32Array(count * 3);
  const normals = new Float32Array(count * 3);
  for (let s = 0; s < count; s++) {
    const r = Math.random();
    let lo = 0;
    let hi = nTris - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (cdf[mid] < r) lo = mid + 1;
      else hi = mid;
    }
    const o = lo * 9;
    let u = Math.random();
    let v = Math.random();
    if (u + v > 1) {
      u = 1 - u;
      v = 1 - v;
    }
    const w = 1 - u - v;
    out[s * 3 + 0] = w * triArray[o + 0] + u * triArray[o + 3] + v * triArray[o + 6];
    out[s * 3 + 1] = w * triArray[o + 1] + u * triArray[o + 4] + v * triArray[o + 7];
    out[s * 3 + 2] = w * triArray[o + 2] + u * triArray[o + 5] + v * triArray[o + 8];

    // Geometric normal of the source triangle: cross(b - a, c - a), normalised.
    const e1x = triArray[o + 3] - triArray[o + 0];
    const e1y = triArray[o + 4] - triArray[o + 1];
    const e1z = triArray[o + 5] - triArray[o + 2];
    const e2x = triArray[o + 6] - triArray[o + 0];
    const e2y = triArray[o + 7] - triArray[o + 1];
    const e2z = triArray[o + 8] - triArray[o + 2];
    let nx = e1y * e2z - e1z * e2y;
    let ny = e1z * e2x - e1x * e2z;
    let nz = e1x * e2y - e1y * e2x;
    const nl = Math.hypot(nx, ny, nz) || 1;
    nx /= nl;
    ny /= nl;
    nz /= nl;
    normals[s * 3 + 0] = nx;
    normals[s * 3 + 1] = ny;
    normals[s * 3 + 2] = nz;
  }
  return { positions: out, normals };
}

/** Centre on the centroid and uniformly scale to a target bounding-sphere radius. */
export function centerAndScale(positions: Float32Array, targetRadius = 1.4): void {
  let cx = 0;
  let cy = 0;
  let cz = 0;
  const n = positions.length / 3;
  for (let i = 0; i < n; i++) {
    cx += positions[i * 3];
    cy += positions[i * 3 + 1];
    cz += positions[i * 3 + 2];
  }
  cx /= n;
  cy /= n;
  cz /= n;
  let maxR = 0;
  for (let i = 0; i < n; i++) {
    const dx = positions[i * 3] - cx;
    const dy = positions[i * 3 + 1] - cy;
    const dz = positions[i * 3 + 2] - cz;
    const r = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (r > maxR) maxR = r;
  }
  const k = targetRadius / Math.max(1e-6, maxR);
  for (let i = 0; i < n; i++) {
    positions[i * 3] = (positions[i * 3] - cx) * k;
    positions[i * 3 + 1] = (positions[i * 3 + 1] - cy) * k;
    positions[i * 3 + 2] = (positions[i * 3 + 2] - cz) * k;
  }
}

/** Build the ambient cloud's per-particle position / direction / seed buffers. */
export function makeAmbientBuffers(count: number): {
  positions: Float32Array;
  dirs: Float32Array;
  seeds: Float32Array;
} {
  const positions = new Float32Array(count * 3);
  const dirs = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const u = Math.random();
    const v = Math.random();
    const theta = u * Math.PI * 2;
    const phi = Math.acos(2 * v - 1);
    const r = 1.5 + Math.random() * 0.5;
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = r * Math.cos(phi);
    const du = Math.random();
    const dv = Math.random();
    const dtheta = du * Math.PI * 2;
    const dphi = Math.acos(2 * dv - 1);
    dirs[i * 3] = Math.sin(dphi) * Math.cos(dtheta);
    dirs[i * 3 + 1] = Math.sin(dphi) * Math.sin(dtheta);
    dirs[i * 3 + 2] = Math.cos(dphi);
    seeds[i] = Math.random();
  }
  return { positions, dirs, seeds };
}

/** Per-particle random seeds for the brain points. */
export function makeSeeds(count: number): Float32Array {
  const seeds = new Float32Array(count);
  for (let i = 0; i < count; i++) seeds[i] = Math.random();
  return seeds;
}

/**
 * Bake a per-particle cavity-occlusion value (0 = exposed ridge, 1 = deep in a
 * fold) by measuring local point density via a spatial hash. Folds (sulci) pack
 * opposing walls close together, so points there have far more neighbours than
 * points on exposed gyri — that density difference is what reads as depth.
 * Runs once at load; O(n · neighbours).
 */
export function computeOcclusion(positions: Float32Array, radius: number): Float32Array {
  const n = positions.length / 3;
  const cell = radius;
  const inv = 1 / cell;
  const r2 = radius * radius;
  const hash = (ix: number, iy: number, iz: number) =>
    (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791);

  // Bucket point indices by grid cell.
  const grid = new Map<number, number[]>();
  for (let i = 0; i < n; i++) {
    const key = hash(
      Math.floor(positions[i * 3] * inv),
      Math.floor(positions[i * 3 + 1] * inv),
      Math.floor(positions[i * 3 + 2] * inv),
    );
    const bucket = grid.get(key);
    if (bucket) bucket.push(i);
    else grid.set(key, [i]);
  }

  // Count neighbours within `radius` across the 27 surrounding cells.
  const counts = new Float32Array(n);
  let mean = 0;
  for (let i = 0; i < n; i++) {
    const px = positions[i * 3];
    const py = positions[i * 3 + 1];
    const pz = positions[i * 3 + 2];
    const cx = Math.floor(px * inv);
    const cy = Math.floor(py * inv);
    const cz = Math.floor(pz * inv);
    let count = 0;
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (let dz = -1; dz <= 1; dz++) {
          const bucket = grid.get(hash(cx + dx, cy + dy, cz + dz));
          if (!bucket) continue;
          for (let b = 0; b < bucket.length; b++) {
            const j = bucket[b];
            const ex = positions[j * 3] - px;
            const ey = positions[j * 3 + 1] - py;
            const ez = positions[j * 3 + 2] - pz;
            if (ex * ex + ey * ey + ez * ez <= r2) count++;
          }
        }
      }
    }
    counts[i] = count;
    mean += count;
  }
  mean /= Math.max(1, n);

  // Normalise relative to the mean: ridges (≈ mean) → 0, folds (≳ 2× mean) → 1.
  const lo = mean * 0.75;
  const span = Math.max(1, mean * 1.4);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = (counts[i] - lo) / span;
    out[i] = t < 0 ? 0 : t > 1 ? 1 : t;
  }
  return out;
}
