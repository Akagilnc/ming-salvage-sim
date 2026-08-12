import type { SecretOrder } from "./types";

export const shouldAutoOpenSecretOrdersAfterSettlement = (
  orders: SecretOrder[], currentTurn: number,
) => orders.some((order) =>
  (order.dossier_progress || []).some((report) => report.turn === currentTurn - 1),
);

export const shouldAutoOpenClosedIssuesAfterSettlement = () => false;
