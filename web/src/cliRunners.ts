import type { CliRunnerChoice } from "./types";

/**
 * CLI Runner 下拉选项接缝（menuPage + gameMenu 共吃）。
 *
 * 单一真源在后端 ming_sim.cli_backend.cli_runner_choices()（membership=_CLI_BACKENDS；
 * GATE_CLI_RUNNERS ⊂ 该集且不含 agy），经 /api/menu/status 与 /api/llm/config 的
 * `cli_runners` 字段下发。前端不各自硬编码 option 列表（#1274 W1）。
 *
 * 端点未下发时回落下方常量——顺序/名单锚 _CLI_BACKENDS，防旧后端/残缺 fixture 漂。
 */
// Anchor: ming_sim.cli_backend._CLI_BACKENDS / cli_runner_choices()
export const CLI_RUNNER_FALLBACK: readonly CliRunnerChoice[] = [
  { value: "agy", label: "agy（Gemini）" },
  { value: "codex", label: "codex" },
  { value: "claude", label: "claude" },
  { value: "cursor", label: "cursor" },
  { value: "kimi", label: "kimi" },
  { value: "grok", label: "grok" },
] as const;

/** Resolve runner dropdown options: backend list wins; else fallback constant. */
export function cliRunnerOptions(
  runners?: readonly CliRunnerChoice[] | null,
): CliRunnerChoice[] {
  if (runners && runners.length > 0) {
    return runners.map((r) => ({ value: r.value, label: r.label || r.value }));
  }
  return CLI_RUNNER_FALLBACK.map((r) => ({ value: r.value, label: r.label }));
}
