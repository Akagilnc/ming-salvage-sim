import React from "react";
import { Loader2, Trash2 } from "lucide-react";
import { api, normalizeApiError } from "../api";
import type { MenuCampaign, MenuStatus } from "../types";

export function MenuPage({
  status,
  onRefresh,
  onEnterGame,
  error,
  setError,
}: {
  status: MenuStatus | null;
  onRefresh: () => Promise<MenuStatus>;
  onEnterGame: () => Promise<void>;
  error: string;
  setError: (msg: string) => void;
}) {
  const [busy, setBusy] = React.useState<string>("");
  const [showApiForm, setShowApiForm] = React.useState(false);
  const [showSaveList, setShowSaveList] = React.useState(false);

  const guard = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (err: any) {
      setError(err?.message || String(err));
    } finally {
      setBusy("");
    }
  };

  const onNewGame = () =>
    guard("新游戏中...", async () => {
      if (status?.has_main_db && !window.confirm("将覆盖当前主进度，是否继续？建议先在游戏中保存为存档。")) return;
      await api("/api/menu/new_game", { method: "POST" });
      await onEnterGame();
    });

  const onContinue = () =>
    guard("载入上次进度...", async () => {
      await api("/api/menu/continue", { method: "POST" });
      await onEnterGame();
    });

  const onLoadSave = (name: string) =>
    guard(`载入「${name}」...`, async () => {
      await api(`/api/menu/load_save/${encodeURIComponent(name)}`, { method: "POST" });
      await onEnterGame();
    });

  const hasKey = !!status?.has_api_key;
  const hasMainDb = !!status?.has_main_db;
  const saves = status?.saves || [];
  const campaigns = status?.campaigns || [];

  return (
    <div className="menu-screen">
      <div className="menu-poster">
        <img src="/steam_assets/主宣传图.jpg" alt="明末：力挽狂澜" />
      </div>

      <h1 className="menu-title">明末：力挽狂澜</h1>

      <div className="menu-panel">
        <p className="menu-subtitle">崇祯元年正月 · 召大臣议天下事</p>

        {!hasKey && (
          <div className="menu-notice">尚未配置 API 接口。请先「设置 API」。</div>
        )}
        {error && <div className="menu-error">{error}</div>}

        <div className="menu-buttons">
          <button className="menu-btn primary" disabled={!hasKey || !!busy} onClick={onNewGame}>
            开始新游戏
          </button>
          <button className="menu-btn" disabled={!hasKey || !hasMainDb || !!busy} onClick={onContinue} title={hasMainDb ? "" : "无上次进度"}>
            继续
          </button>
          <button className="menu-btn" disabled={!hasKey || !!busy || !saves.length} onClick={() => setShowSaveList(true)} title={saves.length ? "" : "暂无存档"}>
            加载存档 {saves.length ? `(${saves.length})` : ""}
          </button>
          <button className="menu-btn" disabled={!!busy} onClick={() => setShowApiForm(true)}>
            设置 API {hasKey ? "" : "（必需）"}
          </button>
        </div>

        {busy && <div className="menu-busy">{busy}</div>}
        {hasKey && status?.llm && (
          <div className="menu-llm-info">
            当前接口：{status.llm.base_url} · {status.llm.model}
          </div>
        )}
      </div>

      {showApiForm && (
        <ApiSettingsModal
          initial={status?.llm}
          onClose={() => setShowApiForm(false)}
          onSaved={async () => {
            setShowApiForm(false);
            await onRefresh();
          }}
        />
      )}

      {showSaveList && (
        <SaveListModal
          campaigns={campaigns}
          onClose={() => setShowSaveList(false)}
          onLoad={async (name) => {
            setShowSaveList(false);
            await onLoadSave(name);
          }}
          onDelete={async (name) => {
            await api(`/api/menu/saves/${encodeURIComponent(name)}`, { method: "DELETE" });
            await onRefresh();
          }}
        />
      )}
    </div>
  );
}

export function ApiSettingsModal({
  initial,
  onClose,
  onSaved,
}: {
  initial?: {
    base_url: string;
    model: string;
    has_api_key: boolean;
    max_tokens?: number;
    timeout_seconds?: number;
    thinking_level?: string;
    advanced_model?: string;
    advanced_base_url?: string;
    has_advanced_api_key?: boolean;
    advanced_thinking_level?: string;
  };
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [baseUrl, setBaseUrl] = React.useState(initial?.base_url || "https://api.deepseek.com");
  const [model, setModel] = React.useState(initial?.model || "deepseek-chat");
  const [advancedModel, setAdvancedModel] = React.useState(initial?.advanced_model || "");
  const [advancedBaseUrl, setAdvancedBaseUrl] = React.useState(initial?.advanced_base_url || "");
  const [advancedApiKey, setAdvancedApiKey] = React.useState("");
  const [advancedThinkingLevel, setAdvancedThinkingLevel] = React.useState(initial?.advanced_thinking_level || "");
  const [apiKey, setApiKey] = React.useState("");
  const [maxTokens, setMaxTokens] = React.useState(String(initial?.max_tokens || 8000));
  const [timeoutSeconds, setTimeoutSeconds] = React.useState(String(initial?.timeout_seconds || 180));
  const [thinkingLevel, setThinkingLevel] = React.useState(initial?.thinking_level || "");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");

  const onSave = async () => {
    setBusy(true);
    setErr("");
    try {
      const response = await fetch("/api/menu/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: baseUrl.trim(),
          model: model.trim(),
          api_key: apiKey.trim(),
          max_tokens: parseInt(maxTokens) || 8000,
          timeout_seconds: parseFloat(timeoutSeconds) || 180,
          thinking_level: thinkingLevel.trim(),
          advanced_model: advancedModel.trim(),
          advanced_base_url: advancedBaseUrl.trim(),
          advanced_api_key: advancedApiKey.trim(),
          advanced_thinking_level: advancedThinkingLevel.trim(),
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ detail: response.statusText }));
        const detail = normalizeApiError(payload, response.statusText);
        setErr(`code: ${detail.code || "unknown"}\nmessage: ${detail.message || response.statusText}`);
        return;
      }
      await onSaved();
    } catch (e: any) {
      setErr(`code: request_failed\nmessage: ${e?.message || String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="menu-modal-bg" onClick={onClose}>
      <div className="menu-modal" onClick={(e) => e.stopPropagation()}>
        <h2>设置 API</h2>
        <p className="menu-hint">推荐 DeepSeek（中文好、价格便宜）。配置写入本地，不上传。</p>
        <label>
          Base URL
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com" />
        </label>
        <label>
          Model
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="deepseek-chat" />
        </label>
        <label>
          Thinking Level <small className="menu-hint">（空=默认，请填写你的模型支持的值。）</small>
          <input value={thinkingLevel} onChange={(e) => setThinkingLevel(e.target.value)} placeholder="默认" />
        </label>
        <label>
          Advanced Model <small className="menu-hint">（推演 + 打分专用；留空 fallback）</small>
          <input value={advancedModel} onChange={(e) => setAdvancedModel(e.target.value)} placeholder="deepseek-reasoner / gpt-5" />
        </label>
        <label>
          Advanced Base URL <small className="menu-hint">（advanced 专用网关；留空复用主 Base URL）</small>
          <input value={advancedBaseUrl} onChange={(e) => setAdvancedBaseUrl(e.target.value)} placeholder="https://other-gateway/v1" />
        </label>
        <label>
          Advanced API Key{" "}
          <small className="menu-hint">{initial?.has_advanced_api_key ? "(已配置；留空保留)" : "(留空=复用主 API Key)"}</small>
          <input type="password" value={advancedApiKey} onChange={(e) => setAdvancedApiKey(e.target.value)} placeholder={initial?.has_advanced_api_key ? "(已配置；如需更换请重新填写)" : "留空=复用主 Key"} />
        </label>
        <label>
          Advanced Thinking Level <small className="menu-hint">（空=默认，请填写你的模型支持的值。）</small>
          <input value={advancedThinkingLevel} onChange={(e) => setAdvancedThinkingLevel(e.target.value)} placeholder="默认" />
        </label>
        <label>
          Max Tokens
          <input type="number" min={256} max={65536} value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} placeholder="8000" />
        </label>
        <label>
          Timeout Seconds
          <input type="number" min={10} max={900} value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(e.target.value)} placeholder="180" />
        </label>
        <label>
          API Key
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={initial?.has_api_key ? "(已配置；如需更换请重新填写)" : "sk-..."} />
        </label>
        {err && <div className="menu-error">{err}</div>}
        <div className="menu-modal-actions">
          <button onClick={onClose} disabled={busy}>取消</button>
          <button className="primary" onClick={onSave} disabled={busy || !baseUrl.trim() || !model.trim() || (!apiKey.trim() && !initial?.has_api_key)}>
            {busy ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function SaveListModal({
  campaigns,
  onClose,
  onLoad,
  onDelete,
}: {
  campaigns: MenuCampaign[];
  onClose: () => void;
  onLoad: (name: string) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
}) {
  const hasAny = campaigns.some((c) => c.saves.length);
  const [delBusy, setDelBusy] = React.useState("");
  const [delErr, setDelErr] = React.useState("");
  const handleDelete = async (name: string, label?: string) => {
    if (!window.confirm(`删除存档「${label || name}」？此操作不可撤销。`)) return;
    setDelBusy(name);
    setDelErr("");
    try {
      await onDelete(name);
    } catch (e) {
      setDelErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDelBusy("");
    }
  };
  return (
    <div className="menu-modal-bg" onClick={onClose}>
      <div className="menu-modal" onClick={(e) => e.stopPropagation()}>
        <h2>加载存档</h2>
        {delErr ? <div className="menu-error">{delErr}</div> : null}
        {hasAny ? (
          <div className="menu-campaign-list">
            {campaigns.map((c) => (
              <div key={c.campaign_id || "__manual__"} className="menu-campaign">
                <div className="menu-campaign-head">
                  <span>{c.kind === "manual" ? "手动存档" : `战局 ${c.campaign_id.slice(0, 6)}`}</span>
                  {c.current ? <span className="menu-campaign-badge">本局</span> : null}
                </div>
                <ul className="menu-save-list">
                  {c.saves.map((s) => (
                    <li key={s.name} className="menu-save-row">
                      <button className="menu-save-load" onClick={() => onLoad(s.name)}>
                        <span className="save-name">{s.label || s.name}</span>
                        <span className="save-meta">{new Date(s.mtime * 1000).toLocaleString("zh-CN")}</span>
                      </button>
                      <button
                        className="menu-save-del"
                        title="删除存档"
                        disabled={delBusy === s.name}
                        onClick={() => handleDelete(s.name, s.label)}
                      >
                        {delBusy === s.name ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className="menu-empty">暂无存档。</p>
        )}
        <div className="menu-modal-actions">
          <button onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
}
