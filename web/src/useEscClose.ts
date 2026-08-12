import React from "react";
import type { ModalName } from "./types";

// 全局 ESC：按 z-index 优先级，最前面的弹窗先关。layers 按优先级从高到低传入。
export function useEscClose(
  activeModal: ModalName,
  setActiveModal: (modal: ModalName) => void,
  layers: Array<{ open: boolean; close: () => void }>,
) {
  const opensKey = layers.map((layer) => (layer.open ? "1" : "0")).join("");
  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (activeModal === "chat" || activeModal === "edict" || activeModal === "state" || activeModal === "history" || activeModal === "audience_archive" || activeModal === "report" || activeModal === "secret_orders") {
        // 召对/诏书等全屏弹窗最优先
        setActiveModal("none");
        return;
      }
      const top = layers.find((layer) => layer.open);
      if (top) top.close();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // opensKey 追踪各层开关变化；close 均为稳定的 setState。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeModal, opensKey, setActiveModal]);
}
