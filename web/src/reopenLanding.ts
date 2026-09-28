/** #1855：重开落点三种 —— 后端状态口真源，前端不猜。 */

export type ReopenLanding = "audience" | "settlement" | "month";

/** 是否在入局/刷新时直接打开殿上卷（夜未收）。 */
export function opensAudienceOnResume(landing: ReopenLanding | string | null | undefined): boolean {
  return landing === "audience";
}
