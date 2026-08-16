import { useMemo } from "react";
import type { ChatModelChoice } from "@wlilley93/boltrig-web-sdk";

import { buildModelOptions } from "./modelChipOptions";

interface ModelChipOptionsInput {
  choices: ChatModelChoice[];
  defaultAvailable?: boolean;
  defaultModelName?: string | null;
  defaultModelSource?: "personal" | "platform";
  defaultUnavailableReason?: string | null;
}

export function useModelChipOptions(input: ModelChipOptionsInput) {
  return useMemo(() => buildModelOptions({
    choices: input.choices,
    defaultModelName: input.defaultModelName,
    defaultModelSource: input.defaultModelSource,
    defaultAvailable: input.defaultAvailable ?? Boolean(input.defaultModelName),
    defaultUnavailableReason: input.defaultUnavailableReason,
  }), [
    input.choices,
    input.defaultAvailable,
    input.defaultModelName,
    input.defaultModelSource,
    input.defaultUnavailableReason,
  ]);
}
