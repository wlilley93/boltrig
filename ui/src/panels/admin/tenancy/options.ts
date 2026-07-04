import type { Option } from "@/panels/ux";

// The per-workspace roles (boltrig/models/tenancy.py WORKSPACE_ROLES). owner
// administers, admin configures, member operates, viewer reads, agent is a
// non-human seat.
export const WORKSPACE_ROLE_OPTIONS: Option[] = [
  { value: "member", label: "member", hint: "Operates in the workspace." },
  { value: "viewer", label: "viewer", hint: "Read only." },
  { value: "admin", label: "admin", hint: "Configures the workspace." },
  { value: "owner", label: "owner", hint: "Administers the workspace." },
  { value: "agent", label: "agent", hint: "A non-human runtime seat." },
];

export const AI_LEVEL_OPTIONS: Option[] = [
  { value: "org", label: "Organisation", hint: "One key for the whole org." },
  { value: "workspace", label: "Workspace", hint: "A key scoped to one workspace." },
  { value: "user", label: "User", hint: "Your own personal key." },
];

// A closed set of known providers (was free-text). The server accepts any, but a
// Select keeps the common ones honest and one-click.
export const AI_PROVIDER_OPTIONS: Option[] = [
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
  { value: "hermes", label: "Hermes" },
  { value: "vllm", label: "vLLM" },
  { value: "ollama", label: "Ollama" },
];

// Per-provider example models: seed the model field with a sensible default and
// offer one-click suggestions, while still allowing a custom (self-hosted) id.
export const AI_MODEL_SUGGESTIONS: Record<string, string[]> = {
  anthropic: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-4"],
  openai: ["gpt-4o", "gpt-4o-mini", "o3-mini"],
  hermes: ["glm-5-turbo", "glm-5"],
  vllm: ["meta-llama/Llama-3.1-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
  ollama: ["llama3.1", "qwen2.5", "mistral"],
};
