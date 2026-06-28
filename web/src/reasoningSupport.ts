type LlmChannel = "api" | "cli";

function normalizedChannel(channel?: LlmChannel): LlmChannel {
  return channel === "cli" ? "cli" : "api";
}

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
  const effectiveBase = (advancedModel.trim() ? (advancedBaseUrl.trim() || baseUrl) : baseUrl).toLowerCase();
  const modelName = (advancedModel.trim() || model).toLowerCase();
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
  backendChannel,
  currentChannel,
  baseUrl,
  model,
  advancedBaseUrl,
  advancedModel,
  cliRunner,
}: {
  backendSupported?: boolean;
  backendChannel?: LlmChannel;
  currentChannel: LlmChannel;
  baseUrl: string;
  model: string;
  advancedBaseUrl: string;
  advancedModel: string;
  cliRunner: string;
}) {
  if (typeof backendSupported === "boolean" && currentChannel === normalizedChannel(backendChannel)) {
    return backendSupported;
  }
  if (currentChannel === "cli") {
    return cliRunner === "codex" || cliRunner === "claude";
  }
  return fallbackApiReasoningSupported({ baseUrl, model, advancedBaseUrl, advancedModel });
}
