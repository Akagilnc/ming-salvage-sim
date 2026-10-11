import React from "react";
import { api } from "./api";
import type { Directive, GameState, LocalDirectiveItem } from "./types";

// #1902 / #1812 待拍第 6 项：拟诏台手写入口整条退役——玩家不再拟新旨、也不再改稿，
// 旨意只从召对来（#1772）。草稿可见、已发追溯与删旧草稿（DELETE /api/directives/{id}）
// 保留；旧草稿去向由 #1826 的草稿与已发记录承接。
// 共享 error 写入与 latest-wins 代次推进（beginDurableMutation 防旧 done 覆盖）。
// #1764：delete 进行态与失败真因绑所属卡；本地会话态随游戏归属代次，进出局清零。
export function useEdictActions({
  setError,
  setState,
  beginDurableMutation,
}: {
  setError: (error: string) => void;
  setState: React.Dispatch<React.SetStateAction<GameState | null>>;
  beginDurableMutation: () => void;
}) {
  const [localDirectives, setLocalDirectives] = React.useState<LocalDirectiveItem[]>([]);
  const localSeq = React.useRef(0);
  // 游戏归属代次：exit/enter 推进；在飞请求收尾时若代次已变，拒写本地态与 state。
  const ownershipRef = React.useRef(0);

  const resetLocalEdictState = React.useCallback(() => {
    ownershipRef.current += 1;
    localSeq.current = 0;
    setLocalDirectives([]);
  }, []);

  const beginCardRequest = (item: LocalDirectiveItem) => {
    // 每张草案卡至多一条进行态请求：同卡旧行（失败行亦然）被新请求顶掉。
    setLocalDirectives((prev) => [
      ...prev.filter((row) => row.directiveId !== item.directiveId),
      item,
    ]);
  };

  const clearCardRequest = (localKey: string) => {
    setLocalDirectives((prev) => prev.filter((item) => item.localKey !== localKey));
  };

  const failCardRequest = (localKey: string, message: string) => {
    setLocalDirectives((prev) =>
      prev.map((item) =>
        item.localKey === localKey ? { ...item, phase: "failed", error: message } : item,
      ),
    );
  };

  const stillOwns = (ownership: number) => ownershipRef.current === ownership;


  const deleteDirective = async (directiveId: number) => {
    const ownership = ownershipRef.current;
    const localKey = `del-${directiveId}-${++localSeq.current}`;
    beginCardRequest({
      localKey,
      phase: "inflight",
      directiveId,
      op: "delete",
    });
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directiveId}`, { method: "DELETE" });
      if (!stillOwns(ownership)) return;
      clearCardRequest(localKey);
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives } : current));
    } catch (err) {
      if (!stillOwns(ownership)) return;
      const message = err instanceof Error ? err.message : String(err);
      failCardRequest(localKey, message);
      setError(message);
    }
  };

  return {
    localDirectives,
    resetLocalEdictState,
    deleteDirective,
  };
}
