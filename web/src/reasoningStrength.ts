import type { ReasoningStrengthChoice } from "./types";

export function visibleReasoningStrengthChoices(
  choices: ReasoningStrengthChoice[],
  channel: string,
  cliRunner: string,
  floorRunners: readonly string[] = [],
): ReasoningStrengthChoice[] {
  // #1271：off 档实取低的 runner 名单来自后端 cli_reasoning_floor_runners（单源），前端不复制。
  if (channel !== "cli" || !floorRunners.includes(cliRunner)) return choices;
  return choices.map((choice) =>
    choice.value === "off" ? { ...choice, label: `关（${cliRunner} 最低=低）` } : choice
  );
}
