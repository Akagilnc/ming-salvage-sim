import type { CliRunnerChoice } from "./types";

/**
 * CLI Runner 下拉选项接缝（menuPage + gameMenu 共吃）。
 *
 * 单一真源在后端 ming_sim.cli_backend.cli_runner_choices()（membership=_CLI_BACKENDS；
 * GATE_CLI_RUNNERS ⊂ 该集且不含 agy），经 /api/menu/status 与 /api/llm/config 的
 * `cli_runners` 字段下发。前端不各自硬编码 option 列表（#1274 W1）。
 */

/** Runner dropdown options: exactly the backend list; absent list → no options. */
export function cliRunnerOptions(
  runners?: readonly CliRunnerChoice[] | null,
): CliRunnerChoice[] {
  return (runners ?? []).map((r) => ({ value: r.value, label: r.label || r.value }));
}
