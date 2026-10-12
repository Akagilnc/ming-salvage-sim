type LlmChannel = "api" | "cli";

export function canConfigureReasoning({
  backendSupported,
  backendCurrent,
  currentChannel,
  cliRunner,
  cliReasoningRunners,
}: {
  backendSupported?: boolean;
  backendCurrent?: boolean;
  currentChannel: LlmChannel;
  cliRunner: string;
  cliReasoningRunners?: string[];
}) {
  if (backendCurrent && typeof backendSupported === "boolean") {
    return backendSupported;
  }
  // An edited API draft has no backend verdict yet; keep the setting editable.
  // Model/provider capability rules remain exclusively on the backend.
  return currentChannel === "api" || (cliReasoningRunners ?? []).includes(cliRunner);
}
