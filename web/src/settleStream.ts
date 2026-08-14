// 颁诏/续裁共用：消费 SSE 推演流，stage/thinking/text 实时更新进度区，
// 返回结束态：done（已结算）/ decisions（暂停待裁）/ error。
export type SettleStreamOutcome = { kind: "done" | "decisions" | "error"; data: any };

type SettleStreamCallbacks = {
  onStage: (text: string) => void;
  onThinking: (chunk: string) => void;
  onNarrative: (chunk: string) => void;
};

function consumeSettleBlocks(
  blocks: string[],
  callbacks: SettleStreamCallbacks,
): SettleStreamOutcome | null {
  for (const block of blocks) {
    let evName = "";
    let dataRaw = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) evName = line.slice(7).trim();
      else if (line.startsWith("data: ")) dataRaw += line.slice(6);
    }
    if (!evName || !dataRaw) continue;
    let data: any = {};
    try { data = JSON.parse(dataRaw); } catch { continue; }
    if (evName === "stage") callbacks.onStage(data.content || "");
    else if (evName === "thinking") callbacks.onThinking(data.content || "");
    else if (evName === "text") callbacks.onNarrative(data.content || "");
    else if (evName === "error") return { kind: "error", data };
    else if (evName === "decisions") return { kind: "decisions", data };
    else if (evName === "done") return { kind: "done", data };
  }
  return null;
}

export async function consumeSettleStream(
  response: Response,
  callbacks: SettleStreamCallbacks,
): Promise<SettleStreamOutcome> {
  if (!response.ok || !response.body) {
    throw new Error(`颁诏失败：HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done: streamDone } = await reader.read();
    if (streamDone) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    const early = consumeSettleBlocks(blocks, callbacks);
    if (early) return early;
  }
  // 流意外关闭时，仍可能留下未以 \n\n 收束的完整终端事件；flush 后再解析一次。
  buffer += decoder.decode();
  if (buffer) {
    const early = consumeSettleBlocks(buffer.split("\n\n"), callbacks);
    if (early) return early;
  }
  return { kind: "error", data: "推演流意外中断。" };
}
