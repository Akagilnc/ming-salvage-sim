import React from "react";
import { api } from "./api";
import type { Directive, GameState, LocalDirectiveItem } from "./types";

// 诏书台动作群：草案登记/编辑/存改/删除/核定/驳回。
// #1341：裸 PATCH /api/decree 与 /api/decree/write 前端死码已删；改稿只走 /api/directives。
// 全部共享 busy/error 写入与 latest-wins 代次推进（beginDurableMutation 防旧 done 覆盖）。
// #1764：create/save/delete 进行态与失败真因绑所属卡；busy 只作禁点互斥，不承载呈现文案。
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

  const beginCardRequest = (item: LocalDirectiveItem) => {
    setLocalDirectives((prev) => [
      ...prev.filter((row) => {
        if (item.directiveId != null) return row.directiveId !== item.directiveId;
        return row.phase !== "failed" || row.directiveId != null;
      }),
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

  const createDirective = async () => {
    if (!directiveText.trim()) return;
    const text = directiveText.trim();
    localSeq.current += 1;
    const localKey = `local-${localSeq.current}`;
    beginCardRequest({ localKey, text, phase: "inflight", op: "create" });
    // 清空 compose；失败时仅在玩家未另写时回填，不覆写等待期间新内容。
    setDirectiveText("");
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>("/api/directives", {
        method: "POST",
        body: JSON.stringify({
          text,
        }),
      });
      clearCardRequest(localKey);
      beginDurableMutation(); // 应用本变更响应前推进代次，作废在飞旧刷新（防旧 done 覆盖）
      setState((current) => (current ? { ...current, directives: data.directives } : current));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      failCardRequest(localKey, message);
      setDirectiveText((current) => (current.trim() === "" ? text : current));
      setError(message);
    }
  };

  const startEditDirective = (directive: Directive) => {
    setLocalDirectives((prev) => prev.filter((item) => item.directiveId !== directive.id));
    setEditingDirectiveId(directive.id);
    setEditingDirectiveText(directive.text);
  };

  const cancelEditDirective = () => {
    setEditingDirectiveId(null);
    setEditingDirectiveText("");
  };

  const saveDirective = async (directive: Directive) => {
    if (!editingDirectiveText.trim()) return;
    const text = editingDirectiveText.trim();
    const localKey = `save-${directive.id}-${++localSeq.current}`;
    beginCardRequest({
      localKey,
      text,
      phase: "inflight",
      directiveId: directive.id,
      op: "save",
    });
    cancelEditDirective();
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directive.id}`, {
        method: "PATCH",
        body: JSON.stringify({ text }),
      });
      clearCardRequest(localKey);
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives } : current));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      failCardRequest(localKey, message);
      // 失败恢复内容绑本卡：回到编辑，写入本次提交快照（不另造草稿系统）。
      setEditingDirectiveId(directive.id);
      setEditingDirectiveText(text);
      setError(message);
    }
  };

  const deleteDirective = async (directiveId: number) => {
    const localKey = `del-${directiveId}-${++localSeq.current}`;
    beginCardRequest({
      localKey,
      text: "",
      phase: "inflight",
      directiveId,
      op: "delete",
    });
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directiveId}`, { method: "DELETE" });
      clearCardRequest(localKey);
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives } : current));
      if (editingDirectiveId === directiveId) {
        cancelEditDirective();
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      failCardRequest(localKey, message);
      setError(message);
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
