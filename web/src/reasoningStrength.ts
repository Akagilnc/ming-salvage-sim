import type { ReasoningStrengthChoice } from "./types";

export function visibleReasoningStrengthChoices(
  choices: ReasoningStrengthChoice[],
  channel: string,
  cliRunner: string
): ReasoningStrengthChoice[] {
  if (channel !== "cli" || cliRunner !== "codex") return choices;
  return choices.map((choice) =>
    choice.value === "off" ? { ...choice, label: "关（codex 最低=低）" } : choice
  );
}
