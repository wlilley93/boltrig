import ReactDOM from "react-dom/client";

import { client } from "../src/client";
import { OnboardingGate } from "../src/components/onboarding/OnboardingGate";
import "../src/styles.css";

client.aiKeys = async () => ({ allow_own_ai_keys: true, ai_keys: [] });
client.chatModelChoices = async () => ({
  status: "ok",
  reason: null,
  choices: [],
  default_model_name: "openai/gpt-5.4",
  default_available: true,
});
client.setAiKey = async () => ({ status: "ok" });
client.updateMeProfile = async ({ display_name }) => ({
  status: "ok",
  profile: { id: "preview", display_name, role: "superadmin" },
});
client.putMeSettings = async () => ({ status: "ok" });

document.documentElement.dataset.theme = "dark";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <OnboardingGate initialAccount={{
    profile: { id: "preview", email: "you@example.com", role: "superadmin" },
    settings: { "setup.onboarding_version": 0 },
  }}>
    <main>Onboarding complete</main>
  </OnboardingGate>,
);
