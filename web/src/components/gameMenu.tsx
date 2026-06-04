import React from "react";
import { Check, Loader2, LogOut, Power, RotateCcw, Save, Settings, Trash2, Upload, X } from "lucide-react";
import { ApiRequestError, api } from "../api";
import type { LLMConfigInfo, SaveEntry } from "../types";

export function GameMenuModal({
  onClose,
  onAfterLoad,
  onExitToMenu,
}: {
  onClose: () => void;
  onAfterLoad: () => void;
  onExitToMenu: () => void;
}) {
  const [tab, setTab] = React.useState<"save" | "load" | "llm" | "reset" | "exit_menu" | "shutdown">("save");
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <section className="center-layer" role="dialog" aria-modal="true" aria-label="游戏菜单">
      <div className="center-scrim" onClick={onClose} />
      <div className="center-modal">
        <header className="center-modal-header">
          <h1>游戏菜单</h1>
          <button className="icon-button" aria-label="关闭弹窗" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="game-menu">
          <nav className="game-menu-tabs">
            <button className={tab === "save" ? "active" : ""} onClick={() => setTab("save")}>
              <Save size={14} /> 保存存档
            </button>
            <button className={tab === "load" ? "active" : ""} onClick={() => setTab("load")}>
              <Upload size={14} /> 加载存档
            </button>
            <button className={tab === "llm" ? "active" : ""} onClick={() => setTab("llm")}>
              <Settings size={14} /> LLM 配置
            </button>
            <button className={tab === "reset" ? "active" : ""} onClick={() => setTab("reset")}>
              <RotateCcw size={14} /> 重开新局
            </button>
            <button className={tab === "exit_menu" ? "active" : ""} onClick={() => setTab("exit_menu")}>
              <LogOut size={14} /> 回到主菜单
            </button>
            <button className={tab === "shutdown" ? "active" : ""} onClick={() => setTab("shutdown")}>
              <Power size={14} /> 退出游戏
            </button>
          </nav>
          <div className="game-menu-body">
            {tab === "save" ? <SaveTab /> : null}
            {tab === "load" ? <LoadTab onAfterLoad={onAfterLoad} /> : null}
            {tab === "llm" ? <LLMConfigTab /> : null}
            {tab === "reset" ? <ResetTab onAfterReset={onAfterLoad} /> : null}
            {tab === "exit_menu" ? <ExitToMenuTab onExit={onExitToMenu} /> : null}
            {tab === "shutdown" ? <ShutdownTab /> : null}
          </div>
        </div>
      </div>
    </section>
  );
}

export function SaveTab() {
  const [name, setName] = React.useState("");
  const [saves, setSaves] = React.useState<SaveEntry[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const [err, setErr] = React.useState("");

  const refresh = React.useCallback(async () => {
    try {
      const data = await api<{ saves: SaveEntry[] }>("/api/saves");
      setSaves(data.saves);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const onSave = async () => {
    if (!name.trim()) {
      setErr("请填存档名。");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await api<{ save: { name: string }; saves: SaveEntry[] }>("/api/saves", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      setMsg(`已保存为 ${name.trim()}.db`);
      setName("");
      await refresh();
    } catch (e) {
      const detail = e instanceof ApiRequestError ? e.detail : null;
      setErr(detail ? `code: ${detail.code || "unknown"}\nmessage: ${detail.message || (e instanceof Error ? e.message : String(e))}` : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="menu-section">
      <h3>保存当前局</h3>
      <p className="menu-hint">将当前 DB 热备到 data/saves/&lt;名字&gt;.db。同名直接覆盖。</p>
      <div className="menu-row">
        <input
          className="menu-input"
          placeholder="存档名（字母/数字/._-）"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={busy}
        />
        <button className="menu-btn primary" onClick={onSave} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <Save size={14} />} 保存
        </button>
      </div>
      {msg ? <div className="menu-success">{msg}</div> : null}
      {err ? <div className="menu-error">{err}</div> : null}
      <h4>现有存档</h4>
      <SavesList saves={saves} onRefresh={refresh} />
    </section>
  );
}

export function LoadTab({ onAfterLoad }: { onAfterLoad: () => void }) {
  const [saves, setSaves] = React.useState<SaveEntry[]>([]);
  const [busy, setBusy] = React.useState("");
  const [err, setErr] = React.useState("");
  const refresh = React.useCallback(async () => {
    try {
      const data = await api<{ saves: SaveEntry[] }>("/api/saves");
      setSaves(data.saves);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);
  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const onLoad = async (n: string) => {
    if (!window.confirm(`确定加载 ${n}.db？当前未保存进度会丢失。`)) return;
    setBusy(n);
    setErr("");
    try {
      await api(`/api/saves/${encodeURIComponent(n)}/load`, { method: "POST" });
      onAfterLoad();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy("");
    }
  };

  return (
    <section className="menu-section">
      <h3>加载存档</h3>
      <p className="menu-hint">选一份覆盖回主 DB。加载后页面会自动重新载入。</p>
      {err ? <div className="menu-error">{err}</div> : null}
      <SavesList saves={saves} onRefresh={refresh} action={onLoad} busy={busy} />
    </section>
  );
}

export function ResetTab({ onAfterReset }: { onAfterReset: () => void }) {
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const [confirmText, setConfirmText] = React.useState("");

  const canReset = confirmText.trim() === "重开";

  const onReset = async () => {
    if (!canReset) return;
    if (!window.confirm("确定重开新局？当前局所有数据将被永久清空（存档目录不动）。")) return;
    setBusy(true);
    setErr("");
    try {
      await api("/api/game/reset", { method: "POST" });
      onAfterReset();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <section className="menu-section">
      <h3>重开新局</h3>
      <p className="menu-hint">
        清空主 DB（聊天记录、回合奏报、局势、ledger 全清），重置到天启七年十二月开局。
        <b>不可撤销</b>。要保留当前局，先到「保存存档」存一份。
      </p>
      <p className="menu-hint">输入「重开」二字以解锁按钮：</p>
      <div className="menu-row">
        <input
          className="menu-input"
          placeholder="输入：重开"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          disabled={busy}
        />
        <button className="menu-btn danger" onClick={onReset} disabled={!canReset || busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <RotateCcw size={14} />} 重开新局
        </button>
      </div>
      {err ? <div className="menu-error">{err}</div> : null}
    </section>
  );
}

export function ExitToMenuTab({ onExit }: { onExit: () => void | Promise<void> }) {
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const onClick = async () => {
    if (!window.confirm("回到主菜单？当前对局会关闭（DB 仍保留，可从「继续上局」回到此处）。")) return;
    setBusy(true);
    setErr("");
    try {
      await onExit();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  return (
    <section className="menu-section">
      <h3>回到主菜单</h3>
      <p className="menu-hint">
        关闭当前游戏会话，回到主菜单。数据库与存档不变；可从主菜单「继续上局」或「加载存档」回到游戏。
      </p>
      <div className="menu-row">
        <button className="menu-btn primary" onClick={onClick} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <LogOut size={14} />} 回到主菜单
        </button>
      </div>
      {err ? <div className="menu-error">{err}</div> : null}
    </section>
  );
}

export function ShutdownTab() {
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const onClick = async () => {
    if (!window.confirm("退出整个游戏？前后端进程都会关闭，未保存的进度会丢失。")) return;
    setBusy(true);
    setErr("");
    try {
      await fetch("/api/menu/shutdown", { method: "POST" });
      // server 已发 SIGTERM 给自己；前端尝试关页面（浏览器可能拦截），否则提示用户。
      setTimeout(() => {
        try { window.close(); } catch { /* noop */ }
      }, 400);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  return (
    <section className="menu-section">
      <h3>退出游戏</h3>
      <p className="menu-hint">
        终止服务进程并尝试关闭浏览器页面。<b>未保存的进度会丢失</b>。要保留当前局，先到「保存存档」。
      </p>
      <div className="menu-row">
        <button className="menu-btn danger" onClick={onClick} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <Power size={14} />} 退出游戏
        </button>
      </div>
      {err ? <div className="menu-error">{err}</div> : null}
    </section>
  );
}

export function SavesList({
  saves,
  onRefresh,
  action,
  busy,
}: {
  saves: SaveEntry[];
  onRefresh: () => void;
  action?: (name: string) => void;
  busy?: string;
}) {
  const [delErr, setDelErr] = React.useState("");
  const onDelete = async (n: string) => {
    if (!window.confirm(`删除 ${n}.db？`)) return;
    try {
      await api(`/api/saves/${encodeURIComponent(n)}`, { method: "DELETE" });
      onRefresh();
    } catch (e) {
      setDelErr(e instanceof Error ? e.message : String(e));
    }
  };
  if (!saves.length) return <div className="menu-empty">尚无存档。</div>;
  return (
    <ul className="saves-list">
      {delErr ? <div className="menu-error">{delErr}</div> : null}
      {saves.map((s) => (
        <li key={s.name} className="saves-row">
          <div className="saves-name">
            <b>{s.name}</b>
            <small>
              {new Date(s.mtime * 1000).toLocaleString()} · {(s.size / 1024).toFixed(1)} KB
            </small>
          </div>
          <div className="saves-actions">
            {action ? (
              <button className="menu-btn primary" disabled={busy === s.name} onClick={() => action(s.name)}>
                {busy === s.name ? <Loader2 size={14} className="spin" /> : <Upload size={14} />} 加载
              </button>
            ) : null}
            <button className="menu-btn danger" onClick={() => onDelete(s.name)}>
              <Trash2 size={14} /> 删
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function LLMConfigTab() {
  const [info, setInfo] = React.useState<LLMConfigInfo | null>(null);
  const [baseUrl, setBaseUrl] = React.useState("");
  const [model, setModel] = React.useState("");
  const [advancedModel, setAdvancedModel] = React.useState("");
  const [advancedBaseUrl, setAdvancedBaseUrl] = React.useState("");
  const [advancedApiKey, setAdvancedApiKey] = React.useState("");
  const [advancedThinkingLevel, setAdvancedThinkingLevel] = React.useState("");
  const [apiKey, setApiKey] = React.useState("");
  const [maxTokens, setMaxTokens] = React.useState("8000");
  const [timeoutSeconds, setTimeoutSeconds] = React.useState("180");
  const [thinkingLevel, setThinkingLevel] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const [err, setErr] = React.useState("");

  React.useEffect(() => {
    api<LLMConfigInfo>("/api/llm/config")
      .then((data) => {
        setInfo(data);
        setBaseUrl(data.base_url);
        setModel(data.model);
        setAdvancedModel(data.advanced_model || "");
        setAdvancedBaseUrl(data.advanced_base_url || "");
        setAdvancedThinkingLevel(data.advanced_thinking_level || "");
        setMaxTokens(String(data.max_tokens || 8000));
        setTimeoutSeconds(String(data.timeout_seconds || 180));
        setThinkingLevel(data.thinking_level || "");
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  const onSave = async () => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const data = await api<LLMConfigInfo>("/api/llm/config", {
        method: "POST",
        body: JSON.stringify({
          base_url: baseUrl,
          model,
          api_key: apiKey,
          max_tokens: parseInt(maxTokens) || 8000,
          timeout_seconds: parseFloat(timeoutSeconds) || 180,
          thinking_level: thinkingLevel.trim(),
          advanced_model: advancedModel,
          advanced_base_url: advancedBaseUrl,
          advanced_api_key: advancedApiKey.trim() ? advancedApiKey : "__keep__",
          advanced_thinking_level: advancedThinkingLevel.trim(),
        }),
      });
      setInfo((cur) => (cur ? { ...cur, ...data } : null));
      setApiKey("");
      setAdvancedApiKey("");
      setMsg("已生效并写入 data/runtime_llm.json。");
    } catch (e) {
      const detail = e instanceof ApiRequestError ? e.detail : null;
      setErr(detail ? `code: ${detail.code || "unknown"}\nmessage: ${detail.message || (e instanceof Error ? e.message : String(e))}` : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="menu-section">
      <h3>LLM 配置</h3>
      <p className="menu-hint">
        立即生效并写入 <code>data/runtime_llm.json</code>，重启进程后自动加载。api_key 留空保留当前。
      </p>
      <label className="menu-field">
        <span>Base URL</span>
        <input
          className="menu-input"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.openai.com/v1"
        />
      </label>
      <label className="menu-field">
        <span>Model</span>
        <input
          className="menu-input"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="gpt-4o-mini"
        />
      </label>
      <label className="menu-field">
        <span>Thinking Level <small className="menu-hint">（空=默认，请填写你的模型支持的值。）</small></span>
        <input
          className="menu-input"
          value={thinkingLevel}
          onChange={(e) => setThinkingLevel(e.target.value)}
          placeholder="默认"
        />
      </label>
      <label className="menu-field">
        <span>Advanced Model <small className="menu-hint">（推演 + 打分专用，空=与 Model 一致）</small></span>
        <input
          className="menu-input"
          value={advancedModel}
          onChange={(e) => setAdvancedModel(e.target.value)}
          placeholder="deepseek-reasoner / gpt-5（留空 fallback）"
        />
      </label>
      <label className="menu-field">
        <span>Advanced Base URL <small className="menu-hint">（advanced 专用网关，空=与 Base URL 一致）</small></span>
        <input
          className="menu-input"
          value={advancedBaseUrl}
          onChange={(e) => setAdvancedBaseUrl(e.target.value)}
          placeholder="https://other-gateway/v1（留空复用主 Base URL）"
        />
      </label>
      <label className="menu-field">
        <span>
          Advanced API Key{" "}
          {info?.has_advanced_api_key ? (
            <small className="ok">（当前已设置）</small>
          ) : (
            <small className="menu-hint">（空=复用主 API Key）</small>
          )}
        </span>
        <input
          className="menu-input"
          type={show ? "text" : "password"}
          value={advancedApiKey}
          onChange={(e) => setAdvancedApiKey(e.target.value)}
          placeholder="留空=复用主 API Key / 保留当前"
        />
      </label>
      <label className="menu-field">
        <span>Advanced Thinking Level <small className="menu-hint">（空=默认，请填写你的模型支持的值。）</small></span>
        <input
          className="menu-input"
          value={advancedThinkingLevel}
          onChange={(e) => setAdvancedThinkingLevel(e.target.value)}
          placeholder="默认"
        />
      </label>
      <label className="menu-field">
        <span>Max Tokens</span>
        <input
          className="menu-input"
          type="number"
          min={256}
          max={65536}
          value={maxTokens}
          onChange={(e) => setMaxTokens(e.target.value)}
          placeholder="8000"
        />
      </label>
      <label className="menu-field">
        <span>Timeout Seconds</span>
        <input
          className="menu-input"
          type="number"
          min={10}
          max={900}
          value={timeoutSeconds}
          onChange={(e) => setTimeoutSeconds(e.target.value)}
          placeholder="180"
        />
      </label>
      <label className="menu-field">
        <span>
          API Key{" "}
          {info?.has_api_key ? <small className="ok">（当前已设置）</small> : <small className="warn">（未设置）</small>}
        </span>
        <div className="menu-row">
          <input
            className="menu-input"
            type={show ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={info?.has_api_key ? "留空保留当前" : "请输入"}
            autoComplete="off"
          />
          <button className="menu-btn" type="button" onClick={() => setShow((v) => !v)}>
            {show ? "隐" : "显"}
          </button>
        </div>
      </label>
      <div className="menu-row">
        <button className="menu-btn primary" onClick={onSave} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <Check size={14} />} 保存并应用
        </button>
      </div>
      {msg ? <div className="menu-success">{msg}</div> : null}
      {err ? <div className="menu-error">{err}</div> : null}
    </section>
  );
}
