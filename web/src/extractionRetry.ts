import type { ExtractionPendingStatus } from "./types";

export type ExtractionRetryProgress = {
  onStage?: (text: string) => void;
};

/**
 * #501 AC8 / #1312：补写重试走既有 SSE stage/done 形（与 settle stream 同消费形）。
 * 成功且 pending 归零后，与 SSE end 共用公共卷轴失效出口。
 */
export async function retryAudienceStoryExtraction(
  onScrollSettled: () => void,
  progress?: ExtractionRetryProgress,
): Promise<ExtractionPendingStatus> {
  const response = await fetch("/api/audience/extraction/retry", { method: "POST" });
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    const detail = (body as { detail?: unknown } | null)?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object"
          ? String((detail as { message?: string }).message || "").trim()
          : "";
    throw new Error(message || `补写账本失败：HTTP ${response.status}`);
  }
  if (!response.body) {
    throw new Error(`补写账本失败：HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const acc: {
    done: ExtractionPendingStatus | undefined;
    error: string;
  } = { done: undefined, error: "" };

  const consumeBlocks = (blocks: string[]) => {
    for (const block of blocks) {
      let evName = "";
      let dataRaw = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) evName = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataRaw += line.slice(6);
      }
      if (!evName || !dataRaw) continue;
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(dataRaw) as Record<string, unknown>;
      } catch {
        continue;
      }
      if (evName === "stage") {
        progress?.onStage?.(String(data.content || ""));
      } else if (evName === "error") {
        acc.error = String(data.message || "补写账本失败。");
      } else if (evName === "done") {
        acc.done = {
          night_id: Number(data.night_id || 0),
          count: Number(data.count || 0),
          pending: Array.isArray(data.pending)
            ? (data.pending as ExtractionPendingStatus["pending"])
            : [],
        };
      }
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    consumeBlocks(blocks);
    if (acc.error || acc.done) break;
  }
  buffer += decoder.decode();
  if (buffer && !acc.error && !acc.done) {
    consumeBlocks(buffer.split("\n\n"));
  }

  if (acc.error) throw new Error(acc.error);
  if (!acc.done) throw new Error("补写账本推演流意外中断。");

  if (Number(acc.done.count || 0) === 0) onScrollSettled();
  return acc.done;
}
