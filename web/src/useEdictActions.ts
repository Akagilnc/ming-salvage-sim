import React from "react";
import { api } from "./api";
import type { Directive, GameState, LocalDirectiveItem } from "./types";

// 诏书台动作群：草案登记/编辑/存改/删除/核定/驳回。
// #1341：裸 PATCH /api/decree 与 /api/decree/write 前端死码已删；改稿只走 /api/directives。
// 全部共享 busy/error 写入与 latest-wins 代次推进（beginDurableMutation 防旧 done 覆盖）。
// #1764：create 在飞项为本地会话态——提交即绑卡；失败回填到卡；刷新后消失。
export function useEdictActions({
  setBusy,
  setError,
  setState,
  beginDurableMutation,
}: {
  setBusy: (busy: string) => void;
  setError: (error: string) => void;
  setState: React.Dispatch<React.SetStateAction<GameState | null>>;
  beginDurableMutation: () => void;
}) {
  const [directiveText, setDirectiveText] = React.useState("");
  const [editingDirectiveId, setEditingDirectiveId] = React.useState<number | null>(null);
  const [editingDirectiveText, setEditingDirectiveText] = React.useState("");
  const [localDirectives, setLocalDirectives] = React.useState<LocalDirectiveItem[]>([]);
  const localSeq = React.useRef(0);

  const createDirective = async () => {
    if (!directiveText.trim()) return;
    // #1300：无反馈时延的呈现补丁——同步 LLM 抽取仍在请求路径内（禁先登记后异步），
    // busy 只作禁写互斥；#1764 主反馈改绑在飞卡，compose 不再挂 busy-line。
    const text = directiveText.trim();
    localSeq.current += 1;
    const localKey = `local-${localSeq.current}`;
    setLocalDirectives((prev) => [
      ...prev.filter((item) => item.phase !== "failed"),
      { localKey, text, phase: "inflight" },
    ]);
    setDirectiveText("");
    setBusy("旨意结构抽取中…");
    setError("");
    const stageTimer = window.setTimeout(() => {
      setBusy("登记诏书草案…");
    }, 2500);
    try {
      const data = await api<{ directives: Directive[] }>("/api/directives", {
        method: "POST",
        body: JSON.stringify({
          text,
        }),
      });
      setLocalDirectives((prev) => prev.filter((item) => item.localKey !== localKey));
      beginDurableMutation();  // 应用本变更响应前推进代次，作废在飞旧刷新（防旧 done 覆盖）
      setState((current) => (current ? { ...current, directives: data.directives } : current));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setLocalDirectives((prev) =>
        prev.map((item) =>
          item.localKey === localKey
            ? { ...item, phase: "failed", error: message }
            : item,
        ),
      );
      // 失败回填 compose，便于同一「新增草案」加速器再点（0047；非新流程）。
      setDirectiveText(text);
      setError(message);
    } finally {
      window.clearTimeout(stageTimer);
      setBusy("");
    }
  };

  const startEditDirective = (directive: Directive) => {
    setEditingDirectiveId(directive.id);
    setEditingDirectiveText(directive.text);
  };

  const cancelEditDirective = () => {
    setEditingDirectiveId(null);
    setEditingDirectiveText("");
  };

  const saveDirective = async (directive: Directive) => {
    if (!editingDirectiveText.trim()) return;
    // #1300：修改草案同样走同步旨意抽取，呈现分段 busy。
    setBusy("旨意结构抽取中…");
    setError("");
    const stageTimer = window.setTimeout(() => {
      setBusy("修改草案…");
    }, 2500);
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directive.id}`, {
        method: "PATCH",
        body: JSON.stringify({ text: editingDirectiveText.trim() }),
      });
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives } : current));
      cancelEditDirective();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      window.clearTimeout(stageTimer);
      setBusy("");
    }
  };

  const deleteDirective = async (directiveId: number) => {
    setBusy("删除草案");
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directiveId}`, { method: "DELETE" });
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives } : current));
      if (editingDirectiveId === directiveId) {
        cancelEditDirective();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const confirmDirective = async (directiveId: number) => {
    setBusy("核定大臣拟旨");
    setError("");
    try {
      const data = await api<{ directives: Directive[]; pending_count: number }>(`/api/directives/${directiveId}/confirm`, { method: "POST" });
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const rejectDirective = async (directiveId: number) => {
    setBusy("驳回大臣拟旨");
    setError("");
    try {
      const data = await api<{ directives: Directive[]; pending_count: number }>(`/api/directives/${directiveId}/reject`, { method: "POST" });
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  return {
    directiveText,
    setDirectiveText,
    editingDirectiveId,
    editingDirectiveText,
    setEditingDirectiveText,
    localDirectives,
    createDirective,
    startEditDirective,
    cancelEditDirective,
    saveDirective,
    deleteDirective,
    confirmDirective,
    rejectDirective,
  };
}
