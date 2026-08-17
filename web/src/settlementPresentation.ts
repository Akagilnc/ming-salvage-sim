import type { SecretOrder } from "./types";

export const shouldAutoOpenSecretOrdersAfterSettlement = (
  orders: SecretOrder[], currentTurn: number,
) => orders.some((order) =>
  (order.dossier_progress || []).some((report) => report.turn === currentTurn - 1),
);

export const shouldAutoOpenClosedIssuesAfterSettlement = () => false;

/** #1234：年月核账态标 —— 全由服务端 settlement_display 下发驱动，客户端不自判。 */
export function yearMonthLabel(turn: {
  year: number;
  period: number;
  settlement_display?: boolean;
}): string {
  const base = `${turn.year} 年 ${turn.period} 月`;
  return turn.settlement_display ? `${base} · 核账` : base;
}
