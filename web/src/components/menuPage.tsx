import React from "react";
import { Loader2, Trash2 } from "lucide-react";
import { api, normalizeApiError } from "../api";
import { cliRunnerOptions } from "../cliRunners";
import { resolveReasoningSupported } from "../reasoningSupport";
import { consumeSettleStream } from "../settleStream";
import type { CliModelChoices, CliRunnerChoice, MenuCampaign, MenuStatus, ReasoningStrengthChoice } from "../types";
import { visibleReasoningStrengthChoices } from "../reasoningStrength";
import { CliModelField } from "./cliModelField";

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
  const [showGameSettings, setShowGameSettings] = React.useState(false);

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
      // #1195：继续走 SSE stage 流（settleStream 先例），busy 标签随阶段更新。
      const response = await fetch("/api/menu/continue", { method: "POST" });
      const outcome = await consumeSettleStream(
        response,
        { onStage: (text) => setBusy(text || "载入上次进度..."), onThinking: () => {}, onNarrative: () => {} },
        { httpErrorLabel: "继续失败" },
      );
      if (outcome.kind === "error") {
        const data = outcome.data;
        const message = typeof data === "string" ? data : (data?.message || "继续失败。");
        throw new Error(message);
      }
      await onEnterGame();
    });

  const onLoadSave = (name: string) =>
    guard(`载入「${name}」...`, async () => {
      await api(`/api/menu/load_save/${encodeURIComponent(name)}`, { method: "POST" });
      await onEnterGame();
    });

  const hasKey = !!status?.has_api_key;
  const llmReady = !!(status?.llm_ready ?? status?.has_api_key);
  const isCli = status?.llm?.channel === "cli";
  const currentBackend = isCli
    ? `CLI · ${status?.llm?.cli_runner || "agy"}${status?.llm?.cli_model ? ` · ${status.llm.cli_model}` : ""}`
    : `${status?.llm?.base_url || ""} · ${status?.llm?.model || ""}`;
  const hasMainDb = !!status?.has_main_db;
  const saves = status?.saves || [];
  const campaigns = status?.campaigns || [];

  return (
    <div className="menu-screen">
      <div className="menu-poster">
        <img src="/steam_assets/主宣传图.jpg" alt="残明朱批：崇祯" />
      </div>

      <header className="menu-header">
        <h1 className="menu-title">
          <img className="menu-logo" src="/steam_assets/game-logo.png" alt="残明朱批：崇祯" />
        </h1>
        <p className="menu-tagline">「朕已知悉」</p>
      </header>

      <div className="menu-panel">
        {!llmReady && (
          <div className="menu-notice">尚未配置 LLM 后端。请先「模型后端」。</div>
        )}
        {error && <div className="menu-error">{error}</div>}

        <div className="menu-buttons">
          <button className="menu-btn primary" disabled={!llmReady || !!busy} onClick={onNewGame}>
            开始新游戏
          </button>
          <button className="menu-btn" disabled={!llmReady || !hasMainDb || !!busy} onClick={onContinue} title={hasMainDb ? "" : "无上次进度"}>
            继续
          </button>
          <button className="menu-btn" disabled={!llmReady || !!busy || !saves.length} onClick={() => setShowSaveList(true)} title={saves.length ? "" : "暂无存档"}>
            加载存档 {saves.length ? `(${saves.length})` : ""}
          </button>
          <div className="menu-divider" />
          <button className="menu-btn subtle" disabled={!!busy} onClick={() => setShowApiForm(true)}>
            模型后端 {hasKey || llmReady ? "" : "（必需）"}
          </button>
          <button className="menu-btn subtle" disabled={!!busy} onClick={() => setShowGameSettings(true)}>
            游戏设置
          </button>
        </div>

        {busy && (
          <div className="menu-busy">
            <Loader2 size={15} className="spin" /> {busy}
          </div>
        )}
        {llmReady && status?.llm && (
          <div className="menu-llm-info">
            当前后端：{currentBackend}
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

      {showGameSettings && (
        <GameSettingsModal
          initial={status?.game_settings}
          onClose={() => setShowGameSettings(false)}
          onSaved={async () => {
            setShowGameSettings(false);
            await onRefresh();
          }}
        />
      )}
    </div>
  );
}

export function GameSettingsModal({
  initial,
  onClose,
  onSaved,
}: {
  initial?: { hitl_min_decisions: number };
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [minDecisions, setMinDecisions] = React.useState<number>(
    initial?.hitl_min_decisions ?? 1
  );
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");

  const onSave = async () => {
    setBusy(true);
    setErr("");
    try {
      await api("/api/menu/game_settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hitl_min_decisions: minDecisions }),
      });
      await onSaved();
    } catch (e: any) {
      setErr(e?.message || String(e));
      setBusy(false);
    }
  };

  return (
    <div className="menu-modal-bg" onClick={onClose}>
      <div className="menu-modal" onClick={(e) => e.stopPropagation()}>
        <h2>游戏设置</h2>
        {err && <div className="menu-error">{err}</div>}
        <label>
          每回合最少重大抉择数{" "}
          <small className="menu-hint">
            （月末推演至少弹几个需皇帝亲裁的决策点。0=不强制，盘面有大事才弹；改动下一回合生效。）
          </small>
          <select
            value={minDecisions}
            onChange={(e) => setMinDecisions(Number(e.target.value))}
          >
            <option value={0}>0 · 不强制</option>
            <option value={1}>1 · 每回合至少 1 个</option>
            <option value={2}>2 · 每回合至少 2 个</option>
            <option value={3}>3 · 每回合至少 3 个</option>
            <option value={4}>4 · 每回合至少 4 个</option>
            <option value={5}>5 · 每回合至少 5 个</option>
          </select>
        </label>
        <div className="menu-modal-actions">
          <button onClick={onClose} disabled={busy}>取消</button>
          <button className="primary" onClick={onSave} disabled={busy}>
            {busy ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
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
    reasoning_strength?: string;
    api_reasoning_strength?: string;
    cli_reasoning_strength?: string;
    reasoning_supported?: boolean;
    reasoning_strengths?: ReasoningStrengthChoice[];
    cli_reasoning_runners?: string[];
    channel?: "api" | "cli";
    cli_runner?: string;
    cli_model?: string;
    cli_model_saved?: string;
    cli_model_choices?: CliModelChoices;
    cli_runners?: CliRunnerChoice[];
    cli_timeout_seconds?: number;
  };
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [channel, setChannel] = React.useState<"api" | "cli">(initial?.channel === "cli" ? "cli" : "api");
  const [cliRunner, setCliRunner] = React.useState(initial?.cli_runner || "agy");
  // 用 raw cli_model_saved（空=默认档），不用 resolved cli_model——后者把默认兜底成
  // 模型名会让下拉误判「其他(手填)」并在空保存时钉死字面量（CMR R1）。
  const [cliModel, setCliModel] = React.useState(initial?.cli_model_saved ?? "");
  const [cliTimeout, setCliTimeout] = React.useState(String(initial?.cli_timeout_seconds || 300));
  const [baseUrl, setBaseUrl] = React.useState(initial?.base_url || "https://api.deepseek.com");
  const [model, setModel] = React.useState(initial?.model || "deepseek-chat");
  const [advancedModel, setAdvancedModel] = React.useState(initial?.advanced_model || "");
  const [advancedBaseUrl, setAdvancedBaseUrl] = React.useState(initial?.advanced_base_url || "");
  const [advancedApiKey, setAdvancedApiKey] = React.useState("");
  const normalizeStrength = (value?: string) => {
    const v = (value || "").trim().toLowerCase();
    if (v === "minimal" || v === "disabled" || v === "none") return "off";
    return ["", "off", "low", "medium", "high"].includes(v) ? v : "";
  };
  const [apiReasoningStrength, setApiReasoningStrength] = React.useState(
    normalizeStrength(initial?.api_reasoning_strength || (initial?.channel === "api" ? initial?.reasoning_strength : "") || initial?.thinking_level)
  );
  const [cliReasoningStrength, setCliReasoningStrength] = React.useState(
    normalizeStrength(initial?.cli_reasoning_strength || (initial?.channel === "cli" ? initial?.reasoning_strength : ""))
  );
  const [apiKey, setApiKey] = React.useState("");
  const [maxTokens, setMaxTokens] = React.useState(String(initial?.max_tokens || 8000));
  const [timeoutSeconds, setTimeoutSeconds] = React.useState(String(initial?.timeout_seconds || 180));
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const reasoningChoices = initial?.reasoning_strengths || [
    { value: "", label: "默认" },
    { value: "off", label: "关" },
    { value: "low", label: "低" },
    { value: "medium", label: "中" },
    { value: "high", label: "高" },
  ];
  const backendChannel = initial?.channel === "cli" ? "cli" : "api";
  const normalizedBaseUrl = baseUrl.trim();
  const normalizedModel = model.trim();
  const normalizedAdvancedBaseUrl = advancedBaseUrl.trim();
  const normalizedAdvancedModel = advancedModel.trim();
  const backendReasoningSupportCurrent = channel === backendChannel && (
    channel === "cli"
      ? cliRunner === (initial?.cli_runner || "agy")
      : normalizedBaseUrl === (initial?.base_url || "").trim() &&
        normalizedModel === (initial?.model || "").trim() &&
        normalizedAdvancedBaseUrl === (initial?.advanced_base_url || "").trim() &&
        normalizedAdvancedModel === (initial?.advanced_model || "").trim()
  );
  const reasoningSupported = resolveReasoningSupported({
    backendSupported: initial?.reasoning_supported,
    backendCurrent: backendReasoningSupportCurrent,
    currentChannel: channel,
    baseUrl,
    model,
    advancedBaseUrl,
    advancedModel,
    cliRunner,
    cliReasoningRunners: initial?.cli_reasoning_runners,
  });
  const reasoningStrength = channel === "cli" ? cliReasoningStrength : apiReasoningStrength;
  const setReasoningStrength = channel === "cli" ? setCliReasoningStrength : setApiReasoningStrength;
  const visibleReasoningChoices = visibleReasoningStrengthChoices(reasoningChoices, channel, cliRunner);

  const onSave = async () => {
    setBusy(true);
    setErr("");
    try {
      const response = await fetch("/api/menu/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel,
          cli_runner: cliRunner.trim(),
          cli_model: cliModel.trim(),
          cli_timeout_seconds: parseFloat(cliTimeout) || 300,
          base_url: baseUrl.trim(),
          model: model.trim(),
          api_key: apiKey.trim(),
          max_tokens: parseInt(maxTokens) || 8000,
          timeout_seconds: parseFloat(timeoutSeconds) || 180,
          // 统一选择器已在初始化时把旧 thinking_level 迁进 reasoningStrength；保存清掉旧字段，
          // 否则它仍作隐藏旋钮被后端 fallback 消费、用户选「默认」也清不掉（#358 cmr）。
          thinking_level: "",
          reasoning_strength: reasoningStrength,
          advanced_model: advancedModel.trim(),
          advanced_base_url: advancedBaseUrl.trim(),
          advanced_api_key: advancedApiKey.trim(),
          advanced_thinking_level: "",
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
        <h2>LLM 后端</h2>
        <p className="menu-hint">API 通道用商业模型；CLI 通道用本机 agent（agy/codex/claude），可脱 key。配置写入本地，不上传。</p>
        <label>
          通道
          <select value={channel} onChange={(e) => setChannel(e.target.value === "cli" ? "cli" : "api")}>
            <option value="api">API（OpenAI 兼容）</option>
            <option value="cli">CLI（本机 agent，脱 key）</option>
          </select>
        </label>
        {channel === "cli" && (
          <>
            <label>
              CLI Runner
              <select
                value={cliRunner}
                onChange={(e) => {
                  setCliRunner(e.target.value);
                  setCliModel("");  // 换 runner 归零到默认档，避免旧模型漏进新 runner
                }}
              >
                {cliRunnerOptions(initial?.cli_runners).map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </label>
            <label>
              推理强度
              <select
                name="reasoning_strength"
                value={reasoningStrength}
                disabled={!reasoningSupported}
                onChange={(e) => setReasoningStrength(e.target.value)}
              >
                {visibleReasoningChoices.map((choice) => (
                  <option key={choice.value} value={choice.value}>{choice.label}</option>
                ))}
              </select>
              {!reasoningSupported && (
                <small className="menu-hint">该后端不支持推理强度设置。</small>
              )}
            </label>
            {/* div 而非 label：custom 态 CliModelField 同时渲染 select+input，HTML5 规定
                一个 label 至多含一个可表单关联控件（gemini R2）。深色控件样式见 .menu-cli-field。 */}
            <div className="menu-cli-field">
              <span>CLI Model <small className="menu-hint">（默认档=runner 默认；其他=手填任意 id）</small></span>
              <CliModelField
                key={cliRunner}
                runner={cliRunner}
                choices={initial?.cli_model_choices}
                value={cliModel}
                onChange={setCliModel}
              />
            </div>
            <label>
              CLI Timeout Seconds
              <input type="number" min={30} max={1800} value={cliTimeout} onChange={(e) => setCliTimeout(e.target.value)} placeholder="300" />
            </label>
          </>
        )}
        {channel === "api" && (
          <>
        <label>
          Base URL
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com" />
        </label>
        <label>
          Model
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="deepseek-chat" />
        </label>
        <label>
          推理强度
          <select
            name="reasoning_strength"
            value={reasoningStrength}
            disabled={!reasoningSupported}
            onChange={(e) => setReasoningStrength(e.target.value)}
          >
            {visibleReasoningChoices.map((choice) => (
              <option key={choice.value} value={choice.value}>{choice.label}</option>
            ))}
          </select>
          {!reasoningSupported && (
            <small className="menu-hint">该后端不支持推理强度设置。</small>
          )}
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
          </>
        )}
        {err && <div className="menu-error">{err}</div>}
        <div className="menu-modal-actions">
          <button onClick={onClose} disabled={busy}>取消</button>
          <button className="primary" onClick={onSave} disabled={busy || (channel === "cli" ? !cliRunner.trim() : (!baseUrl.trim() || !model.trim() || (!apiKey.trim() && !initial?.has_api_key)))}>
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
