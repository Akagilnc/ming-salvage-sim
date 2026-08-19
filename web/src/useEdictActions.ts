import React from "react";
import { api } from "./api";
import type { Directive, GameState } from "./types";

// 诏书台动作群：草案登记/编辑/存改/删除/核定/驳回 + 诏文拟写/存改/返工。
// 全部共享 busy/error 写入与 latest-wins 代次推进（beginDurableMutation 防旧 done 覆盖）。
export function useEdictActions({
  setBusy,
  setError,
  setState,
  beginDurableMutation,
  loadState,
  setDecree,
}: {
  setBusy: (busy: string) => void;
  setError: (error: string) => void;
  setState: React.Dispatch<React.SetStateAction<GameState | null>>;
  beginDurableMutation: () => void;
  loadState: () => Promise<unknown>;
  setDecree: (decree: string) => void;
}) {
  const [directiveText, setDirectiveText] = React.useState("");
  const [editingDirectiveId, setEditingDirectiveId] = React.useState<number | null>(null);
  const [editingDirectiveText, setEditingDirectiveText] = React.useState("");

  const createDirective = async () => {
    if (!directiveText.trim()) return;
    // #1300：无反馈时延的呈现补丁——同步 LLM 抽取仍在请求路径内（禁先登记后异步），
    // 仅把 busy 文案改成可读分段，让长等待不「干等无字」。
    setBusy("旨意结构抽取中…");
    setError("");
    const stageTimer = window.setTimeout(() => {
      setBusy("登记诏书草案…");
    }, 2500);
    try {
      const data = await api<{ directives: Directive[] }>("/api/directives", {
        method: "POST",
        body: JSON.stringify({
          text: directiveText.trim(),
        }),
      });
      setDirectiveText("");
      beginDurableMutation();  // 应用本变更响应前推进代次，作废在飞旧刷新（防旧 done 覆盖）
      setState((current) => (current ? { ...current, directives: data.directives } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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

  const writeDecree = async () => {
    setBusy("拟写正式诏书");
    setError("");
    try {
      const data = await api<{ decree: string }>("/api/decree/write", { method: "POST" });
      setDecree(data.decree);
      // write_decree 内部会运行 commit_pending_actions，pending 随之消失；
      // 因此重新获取包含 directives / pending_directive_count 的完整 state。
      await loadState();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const saveDecree = async (text: string) => {
    setBusy("存改诏书");
    setError("");
    try {
      const data = await api<{ decree: string }>("/api/decree", {
        method: "PATCH",
        body: JSON.stringify({ decree: text }),
      });
      setDecree(data.decree);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const resetDecree = () => {
    // 返工：丢弃当前诏文回到御案理政幕。后端旧诏文留着无妨，重新生成即覆盖。
    setDecree("");
    setError("");
  };

  return {
    directiveText,
    setDirectiveText,
    editingDirectiveId,
    editingDirectiveText,
    setEditingDirectiveText,
    createDirective,
    startEditDirective,
    cancelEditDirective,
    saveDirective,
    deleteDirective,
    confirmDirective,
    rejectDirective,
    writeDecree,
    saveDecree,
    resetDecree,
  };
}
