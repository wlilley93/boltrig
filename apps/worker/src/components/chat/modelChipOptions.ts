import type { ChatModelChoice } from "@wlilley93/boltrig-web-sdk";

export interface ChipOption {
  id: string;
  label: string;
  available: boolean;
  disambiguator?: string;
  unavailableReason?: string | null;
}

interface BuildModelOptionsInput {
  choices: ChatModelChoice[];
  defaultModelName?: string | null;
  defaultAvailable: boolean;
  defaultUnavailableReason?: string | null;
}

export function buildModelOptions({
  choices,
  defaultModelName,
  defaultAvailable,
  defaultUnavailableReason,
}: BuildModelOptionsInput): ChipOption[] {
  const duplicateNames = new Map<string, number>();
  choices.forEach((choice) => {
    duplicateNames.set(choice.model_name, (duplicateNames.get(choice.model_name) ?? 0) + 1);
  });

  return [
    {
      id: "",
      label: defaultModelName ? `Automatic · ${defaultModelName}` : "Automatic",
      available: defaultAvailable,
      unavailableReason: defaultUnavailableReason,
    },
    ...choices.map((choice) => ({
      id: choice.id,
      label: choice.model_name,
      available: choice.available,
      disambiguator: duplicateNames.get(choice.model_name)! > 1 ? choice.id : undefined,
      unavailableReason: choice.unavailable_reason,
    })),
  ];
}

export function nextAvailable(
  options: ChipOption[], current: number, direction: 1 | -1,
) {
  let next = current;
  for (let checked = 0; checked < options.length; checked += 1) {
    next = (next + direction + options.length) % options.length;
    if (options[next]?.available) return next;
  }
  return current;
}
