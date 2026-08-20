import React from "react";
import { Check, Loader2, LogOut, Power, RotateCcw, Save, Settings, Trash2, Upload, X } from "lucide-react";
import { ApiRequestError, api } from "../api";
import { cliRunnerOptions } from "../cliRunners";
import { resolveReasoningSupported } from "../reasoningSupport";
import type { LLMConfigInfo, SaveEntry } from "../types";
import { visibleReasoningStrengthChoices } from "../reasoningStrength";
import { CliModelField } from "./cliModelField";

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
        清空主 DB（聊天记录、回合奏报、局势、ledger 全清），重置到开局。
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

// CLI 子进程默认超时（秒），与后端 llm_config.CLI_DEFAULT_TIMEOUT_SECONDS 对齐（#55 跨语言）。
const CLI_DEFAULT_TIMEOUT = 300;

type LLMConfigSavePayload = Omit<LLMConfigInfo, "persisted"> & Partial<Pick<LLMConfigInfo, "persisted">>;

export function mergePersistedSaveSnapshot(
  data: LLMConfigSavePayload,
  cur: LLMConfigInfo | null
): LLMConfigInfo["persisted"] {
  if (data.persisted) return data.persisted;
  const current = cur?.persisted;
  const savedCliSlot = data.channel === "cli";
  return {
    ...(current || {}),
    channel: data.channel,
    base_url: data.base_url,
    model: data.model,
    has_api_key: data.has_api_key,
    max_tokens: data.max_tokens,
    timeout_seconds: data.timeout_seconds,
    thinking_level: data.thinking_level,
    advanced_model: data.advanced_model,
    advanced_base_url: data.advanced_base_url,
    has_advanced_api_key: data.has_advanced_api_key,
    advanced_thinking_level: data.advanced_thinking_level,
    reasoning_strength: data.reasoning_strength,
    api_reasoning_strength: data.api_reasoning_strength ?? (savedCliSlot ? current?.api_reasoning_strength : data.reasoning_strength),
    cli_reasoning_strength: data.cli_reasoning_strength ?? (savedCliSlot ? data.reasoning_strength : current?.cli_reasoning_strength),
    cli_runner: savedCliSlot ? (data.cli_runner || current?.cli_runner) : current?.cli_runner,
    cli_model: savedCliSlot ? (data.cli_model ?? current?.cli_model) : current?.cli_model,
    cli_timeout_seconds: savedCliSlot ? (data.cli_timeout_seconds || current?.cli_timeout_seconds) : current?.cli_timeout_seconds,
  };
}

export function LLMConfigTab() {
  const [info, setInfo] = React.useState<LLMConfigInfo | null>(null);
  const [baseUrl, setBaseUrl] = React.useState("");
  const [model, setModel] = React.useState("");
  const [advancedModel, setAdvancedModel] = React.useState("");
  const [advancedBaseUrl, setAdvancedBaseUrl] = React.useState("");
  const [advancedApiKey, setAdvancedApiKey] = React.useState("");
  const [apiKey, setApiKey] = React.useState("");
  const [maxTokens, setMaxTokens] = React.useState("8000");
  const [timeoutSeconds, setTimeoutSeconds] = React.useState("180");
  const normalizeStrength = (value?: string) => {
    const v = (value || "").trim().toLowerCase();
    if (v === "minimal" || v === "disabled" || v === "none") return "off";
    return ["", "off", "low", "medium", "high"].includes(v) ? v : "";
  };
  const [apiReasoningStrength, setApiReasoningStrength] = React.useState("");
  const [cliReasoningStrength, setCliReasoningStrength] = React.useState("");
  // 通道感知（#51）：局中也能切 API / CLI 通道,不再被强制降级到 api。
  const [channel, setChannel] = React.useState<"api" | "cli">("api");
  const [cliRunner, setCliRunner] = React.useState("agy");
  const [cliModel, setCliModel] = React.useState("");
  const [cliTimeout, setCliTimeout] = React.useState(String(CLI_DEFAULT_TIMEOUT));
  const [show, setShow] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const [err, setErr] = React.useState("");
  const backendChannel = info?.channel === "cli" ? "cli" : "api";
  const normalizedBaseUrl = baseUrl.trim();
  const normalizedModel = model.trim();
  const normalizedAdvancedBaseUrl = advancedBaseUrl.trim();
  const normalizedAdvancedModel = advancedModel.trim();
  const backendReasoningSupportCurrent = channel === backendChannel && (
    channel === "cli"
      ? cliRunner === (info?.cli_runner || "agy")
      : normalizedBaseUrl === (info?.base_url || "").trim() &&
        normalizedModel === (info?.model || "").trim() &&
        normalizedAdvancedBaseUrl === (info?.advanced_base_url || "").trim() &&
        normalizedAdvancedModel === (info?.advanced_model || "").trim()
  );
  const reasoningSupported = resolveReasoningSupported({
    backendSupported: info?.reasoning_supported,
    backendCurrent: backendReasoningSupportCurrent,
    currentChannel: channel,
    baseUrl,
    model,
    advancedBaseUrl,
    advancedModel,
    cliRunner,
    cliReasoningRunners: info?.cli_reasoning_runners,
  });
  const reasoningChoices = info?.reasoning_strengths || [
    { value: "", label: "默认" },
    { value: "off", label: "关" },
    { value: "low", label: "低" },
    { value: "medium", label: "中" },
    { value: "high", label: "高" },
  ];
  const reasoningStrength = channel === "cli" ? cliReasoningStrength : apiReasoningStrength;
  const setReasoningStrength = channel === "cli" ? setCliReasoningStrength : setApiReasoningStrength;
  const visibleReasoningChoices = visibleReasoningStrengthChoices(reasoningChoices, channel, cliRunner);

  React.useEffect(() => {
    api<LLMConfigInfo>("/api/llm/config")
      .then((data) => {
        setInfo(data);
        setBaseUrl(data.base_url);
        setModel(data.model);
        setAdvancedModel(data.advanced_model || "");
        setAdvancedBaseUrl(data.advanced_base_url || "");
        setMaxTokens(String(data.max_tokens || 8000));
        setTimeoutSeconds(String(data.timeout_seconds || 180));
        setApiReasoningStrength(normalizeStrength(
          data.persisted?.api_reasoning_strength || (data.channel === "api" ? data.reasoning_strength : "") || data.thinking_level
        ));
        setCliReasoningStrength(normalizeStrength(
          data.persisted?.cli_reasoning_strength || (data.channel === "cli" ? data.reasoning_strength : "")
        ));
        setChannel(data.channel === "cli" ? "cli" : "api");
        // 从已存 CLI 槽(persisted)初始化优先,而非 active cfg.cli_*——API 会话下 cfg.cli_model 可能被
        // cli_model_from_env 兜底成 API model 名,直接回填会把它当用户选项 post 回去(CMR R3 codex)。
        // (存盘响应无 persisted 字段 → 回落 active,channel=cli 时即刚提交值,正确。)
        setCliRunner(data.persisted?.cli_runner || (data.channel === "cli" ? data.cli_runner || "" : "") || "agy");
        setCliModel(data.persisted?.cli_model ?? (data.channel === "cli" ? data.cli_model || "" : ""));
        setCliTimeout(String(data.persisted?.cli_timeout_seconds || data.cli_timeout_seconds || CLI_DEFAULT_TIMEOUT));
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
          // 统一「推理强度」选择器已在 load 时把旧 thinking_level 迁进 reasoningStrength；保存时清掉
          // 旧字段，否则它会作隐藏第二旋钮被后端 fallback 消费、用户选「默认」也清不掉（#358 cmr）。
          thinking_level: "",
          reasoning_strength: reasoningStrength,
          advanced_model: advancedModel,
          advanced_base_url: advancedBaseUrl,
          advanced_api_key: advancedApiKey.trim() ? advancedApiKey : "__keep__",
          advanced_thinking_level: "",
          channel,
          cli_runner: channel === "cli" ? cliRunner : "__keep__",
          cli_model: channel === "cli" ? cliModel : "__keep__",
          cli_timeout_seconds: channel === "cli" ? parseFloat(cliTimeout) || CLI_DEFAULT_TIMEOUT : 0,
        }),
      });
      setInfo((cur) => ({
        ...(cur || data),
        ...data,
        persisted: mergePersistedSaveSnapshot(data, cur),
        cli_model_choices: data.cli_model_choices || cur?.cli_model_choices || {},
        cli_runners: data.cli_runners || cur?.cli_runners,
      }));
      setBaseUrl(data.base_url);
      setModel(data.model);
      setAdvancedModel(data.advanced_model || "");
      setAdvancedBaseUrl(data.advanced_base_url || "");
      // 用服务端归一后的响应同步本地通道/CLI 状态,避免与 info 漂移(Sourcery R1)。
      setChannel(data.channel === "cli" ? "cli" : "api");
      if (data.channel === "cli") {
        setCliReasoningStrength(normalizeStrength(data.reasoning_strength || reasoningStrength));
      } else {
        setApiReasoningStrength(normalizeStrength(data.reasoning_strength || reasoningStrength));
      }
      setCliRunner(data.cli_runner || "agy");
      // cliModel 不从 data.cli_model 回灌：那是 resolved 值（空/__keep__ 会被兜底成
      // 默认名或 cur 的已解析值），灌回会让策展下拉把默认/留空误判成「其他(手填)」。
      // 本地 cliModel 即用户刚提交且通过连通性校验的原值（raw），保留它即可——与加载端
      // 读 persisted.cli_model、menuPage 读 cli_model_saved 一致同走 raw（CMR R3 codex+gemini）。
      setCliTimeout(String(data.cli_timeout_seconds || CLI_DEFAULT_TIMEOUT));
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
        <span>执行通道</span>
        <select
          className="menu-input"
          value={channel}
          onChange={(e) => setChannel(e.target.value === "cli" ? "cli" : "api")}
        >
          <option value="api">API（OpenAI 兼容，需 key）</option>
          <option value="cli">CLI（本地 codex/agy/claude，脱 key）</option>
        </select>
      </label>
      {channel === "cli" ? (
        <>
          <label className="menu-field">
            <span>CLI Runner</span>
            <select
              className="menu-input"
              value={cliRunner}
              onChange={(e) => {
                setCliRunner(e.target.value);
                setCliModel("");  // 换 runner 归零到默认档，避免旧模型漏进新 runner
              }}
            >
              {cliRunnerOptions(info?.cli_runners).map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
          <label className="menu-field">
            <span>推理强度</span>
            <select
              className="menu-input"
              name="reasoning_strength"
              value={reasoningStrength}
              disabled={!reasoningSupported}
              onChange={(e) => setReasoningStrength(e.target.value)}
            >
              {visibleReasoningChoices.map((choice) => (
                <option key={choice.value} value={choice.value}>{choice.label}</option>
              ))}
            </select>
            {!reasoningSupported ? (
              <small className="menu-hint">该后端不支持推理强度设置。</small>
            ) : null}
          </label>
          {/* div 而非 label：custom 态 CliModelField 同时渲染 select+input，HTML5 规定
              一个 label 至多含一个可表单关联控件，两个会无效且无障碍歧义（gemini R2）。 */}
          <div className="menu-field">
            <span>CLI Model <small className="menu-hint">（默认档=runner 默认；其他=手填任意 id）</small></span>
            <CliModelField
              key={cliRunner}
              className="menu-input"
              runner={cliRunner}
              choices={info?.cli_model_choices}
              value={cliModel}
              onChange={setCliModel}
            />
          </div>
          <label className="menu-field">
            <span>CLI 超时（秒）</span>
            <input
              className="menu-input"
              type="number"
              min={30}
              max={1800}
              value={cliTimeout}
              onChange={(e) => setCliTimeout(e.target.value)}
              placeholder="300"
            />
          </label>
        </>
      ) : null}
      {channel === "api" ? (
        <>
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
            <span>推理强度</span>
            <select
              className="menu-input"
              name="reasoning_strength"
              value={reasoningStrength}
              disabled={!reasoningSupported}
              onChange={(e) => setReasoningStrength(e.target.value)}
            >
              {visibleReasoningChoices.map((choice) => (
                <option key={choice.value} value={choice.value}>{choice.label}</option>
              ))}
            </select>
            {!reasoningSupported ? (
              <small className="menu-hint">该后端不支持推理强度设置。</small>
            ) : null}
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
          {/* div 包裹：input+button 两个可表单关联控件，HTML5 规定一个 label 至多含一个。
              用 label htmlFor 单独绑 input 恢复无障碍名称，button 留在 label 外。 */}
          <div className="menu-field">
            <label htmlFor="api-key-input">
              API Key{" "}
              {info?.has_api_key ? <small className="ok">（当前已设置）</small> : <small className="warn">（未设置）</small>}
            </label>
            <div className="menu-row">
              <input
                id="api-key-input"
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
          </div>
        </>
      ) : null}
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
