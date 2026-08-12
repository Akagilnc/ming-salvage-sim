import { api } from "./api";
import type { ExtractionPendingStatus } from "./types";

/** 补写成功且 pending 归零后，与 SSE end 共用公共卷轴失效出口。 */
export async function retryAudienceStoryExtraction(onScrollSettled: () => void): Promise<ExtractionPendingStatus> {
  const data = await api<ExtractionPendingStatus>("/api/audience/extraction/retry", { method: "POST" });
  if (Number(data?.count || 0) === 0) onScrollSettled();
  return data;
}
