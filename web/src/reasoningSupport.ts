type LlmChannel = "api" | "cli";

function fallbackApiReasoningSupported({
  baseUrl,
  model,
  advancedBaseUrl,
  advancedModel,
}: {
  baseUrl: string;
  model: string;
  advancedBaseUrl: string;
  advancedModel: string;
}) {
  const base = baseUrl.trim();
  const advancedBase = advancedBaseUrl.trim();
  const primaryModel = model.trim();
  const advanced = advancedModel.trim();
  const effectiveBase = (advanced ? (advancedBase || base) : base).toLowerCase();
  const modelName = (advanced || primaryModel).toLowerCase();
  if (effectiveBase.includes("deepseek.com")) return false;
  return (
    modelName.startsWith("o1") ||
    modelName.startsWith("o3") ||
    modelName.startsWith("o4") ||
    modelName.startsWith("gpt-5") ||
    effectiveBase.includes("dashscope") ||
    effectiveBase.includes("aliyuncs") ||
    effectiveBase.includes("minimaxi.com") ||
    effectiveBase.includes("minimax.io")
  );
}

export function resolveReasoningSupported({
  backendSupported,
  backendCurrent,
  currentChannel,
  baseUrl,
  model,
  advancedBaseUrl,
  advancedModel,
  cliRunner,
  cliReasoningRunners,
}: {
  backendSupported?: boolean;
  backendCurrent?: boolean;
  currentChannel: LlmChannel;
  baseUrl: string;
  model: string;
  advancedBaseUrl: string;
  advancedModel: string;
  cliRunner: string;
  /** Backend capability list (cli_backend.CLI_REASONING_STRENGTH_RUNNERS). No hardcoded runner names. */
  cliReasoningRunners?: string[];
}) {
  if (backendCurrent && typeof backendSupported === "boolean") {
    return backendSupported;
  }
  if (currentChannel === "cli") {
    // #1271: consume payload capability list; delete codex||claude hardcode (DRY).
    const runners = cliReasoningRunners ?? [];
    return runners.includes(cliRunner);
  }
  return fallbackApiReasoningSupported({ baseUrl, model, advancedBaseUrl, advancedModel });
}
