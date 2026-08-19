import type { ReasoningStrengthChoice } from "./types";

export function visibleReasoningStrengthChoices(
  choices: ReasoningStrengthChoice[],
  channel: string,
  cliRunner: string
): ReasoningStrengthChoice[] {
  // #1271: codex/grok off→low 同缝（cli_backend 传输表）；label 提示最低=低。
  if (channel !== "cli" || (cliRunner !== "codex" && cliRunner !== "grok")) return choices;
  return choices.map((choice) =>
    choice.value === "off" ? { ...choice, label: `关（${cliRunner} 最低=低）` } : choice
  );
}
