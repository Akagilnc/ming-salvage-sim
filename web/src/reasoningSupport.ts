type LlmChannel = "api" | "cli";

export function resolveReasoningSupported({
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
  return currentChannel === "cli" && (cliReasoningRunners ?? []).includes(cliRunner);
}
