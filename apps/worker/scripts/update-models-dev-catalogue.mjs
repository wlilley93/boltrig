import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const API_URL = "https://models.dev/api.json";
const COMMIT_URL = "https://api.github.com/repos/anomalyco/models.dev/commits/dev";
const output = fileURLToPath(new URL("../src/components/onboarding/modelsDevCatalogue.json", import.meta.url));
const SUPPLEMENTAL_PROVIDERS = [
  { id: "actual", name: "Actual Computer", models: [] },
  { id: "arcee", name: "Arcee AI", models: [] },
  { id: "byteplus", name: "BytePlus", models: [] },
  { id: "qianfan", name: "Qianfan", models: [] },
];

const [catalogueResponse, commitResponse] = await Promise.all([
  fetch(API_URL, { headers: { accept: "application/json" } }),
  fetch(COMMIT_URL, { headers: { accept: "application/vnd.github+json" } }),
]);
if (!catalogueResponse.ok || !commitResponse.ok) {
  throw new Error(`models.dev refresh failed (${catalogueResponse.status}/${commitResponse.status})`);
}

const source = await catalogueResponse.json();
const commit = await commitResponse.json();
if (!source || typeof source !== "object" || Array.isArray(source)) {
  throw new Error("models.dev returned an invalid provider catalogue");
}
if (typeof commit.sha !== "string" || !/^[0-9a-f]{40}$/.test(commit.sha)) {
  throw new Error("models.dev returned an invalid source revision");
}

const providers = Object.entries(source).map(([id, raw]) => projectProvider(id, raw));
for (const provider of SUPPLEMENTAL_PROVIDERS) {
  if (!providers.some((entry) => entry.id === provider.id)) providers.push(provider);
}
providers.push({ id: "custom", name: "Custom / self-hosted", models: [] });
providers.sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id));

const payload = {
  source: API_URL,
  revision: commit.sha,
  license: "MIT",
  providers,
};
await writeFile(output, `${JSON.stringify(payload)}\n`, "utf8");
console.log(`Wrote ${providers.length} providers to ${output} at ${commit.sha}`);

function projectProvider(id, raw) {
  if (!safeText(id, 80) || !raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(`invalid provider row: ${id}`);
  }
  const name = safeText(raw.name, 120) ? raw.name : id;
  const models = Object.entries(raw.models ?? {})
    .filter(([modelId, model]) => model?.status !== "deprecated"
      && exactModelIdAllowed(id, modelId))
    .map(([modelId, model]) => projectModel(id, modelId, model))
    .sort((left, right) => (left.name ?? left.id).localeCompare(right.name ?? right.id)
      || left.id.localeCompare(right.id));
  return { id, name, models };
}

function projectModel(providerId, id, raw) {
  if (!safeText(id, 180) || !raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(`invalid model row: ${providerId}/${id}`);
  }
  const name = safeText(raw.name, 180) ? raw.name : id;
  const input = Array.isArray(raw.modalities?.input)
    ? raw.modalities.input.filter((value) => safeText(value, 24)).slice(0, 8)
    : ["text"];
  const projected = { id };
  if (name !== id) projected.name = name;
  if (input.includes("image") || input.includes("vision")) projected.vision = true;
  return projected;
}

function safeText(value, maximum) {
  return typeof value === "string"
    && value.length > 0
    && value.length <= maximum
    && value === value.trim()
    && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
}

function exactModelIdAllowed(providerId, modelId) {
  const value = `${providerId}/${modelId}`;
  if (!/^[A-Za-z0-9][A-Za-z0-9@_.:/-]{0,159}$/.test(value)) return false;
  if (value.split("/").some((part) => ["", ".", ".."].includes(part))) return false;
  const mutable = new Set([
    "auto", "beta", "current", "default", "experimental", "latest", "preview",
    "recommended", "stable",
  ]);
  return !value.split(/[._:/-]/).some((part) => mutable.has(part.toLowerCase()));
}
