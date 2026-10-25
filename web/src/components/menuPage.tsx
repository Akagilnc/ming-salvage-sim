import React from 'react';
import type { Action, Configuration, Settings, Snapshot } from '../types';

export function SettingsForm({ initial, requiredSettings, onSave }: {
  initial: Configuration; requiredSettings: Snapshot['required_settings']; onSave: (settings: Configuration) => void;
}) {
  const [value, setValue] = React.useState(initial);
  return <form className="settings" onSubmit={event => { event.preventDefault(); onSave(value); }}>
    <h2>设置</h2>
    {(['main', 'month'] as const).map(slot => {
      const channel = slot === 'main' ? value : value.month_model ?? { backend: '', model: '', base_url: '', api_key: '', effort: '' };
      const update = (patch: Partial<Settings>) => setValue(slot === 'main' ? { ...value, ...patch } : { ...value, month_model: { ...channel, ...patch } });
      const required = requiredSettings[channel.backend] ?? [];
      return <fieldset key={slot}>
        <legend>{slot === 'main' ? '主模型' : '过月模型'}</legend>
        {slot === 'month' && <p>不填或没填全时，过月整段沿用主模型。</p>}
        <label>后端<select value={channel.backend} onChange={event => update({ backend: event.target.value as Settings['backend'] })}>
          {slot === 'month' && <option value="">沿用主模型</option>}
          <option value="api">OpenAI 兼容 API</option><option value="claude-cli">Claude 命令行宿主</option><option value="codex">Codex 订阅</option><option value="grok">Grok 订阅</option><option value="pi">Pi 订阅</option>
        </select></label>
        <label>模型{required.includes('model') && '（必填）'}<input required={slot === 'main' && required.includes('model')} value={channel.model} onChange={event => update({ model: event.target.value })} /></label>
        {channel.backend === 'api' && <>
          <label>API 地址（必填）<input required={slot === 'main' && required.includes('base_url')} type="url" value={channel.base_url} onChange={event => update({ base_url: event.target.value })} /></label>
          <label>API Key<input type="password" autoComplete="off" value={channel.api_key} onChange={event => update({ api_key: event.target.value })} /></label>
        </>}
        <label>档位<input value={channel.effort} placeholder="留空用宿主默认档" onChange={event => update({ effort: event.target.value })} /></label>
      </fieldset>;
    })}
    <button type="submit">保存设置</button>
  </form>;
}

export function MenuPage({ snapshot, onAction, busy, error }: {
  snapshot: Snapshot; onAction: (action: Action) => Promise<void>; busy: boolean; error: string;
}) {
  const [panel, setPanel] = React.useState<'saves' | 'settings' | null>(null);
  return <main className="menu-screen">
    <img className="menu-poster" src="/steam_assets/主宣传图.jpg" alt="" />
    <div className="menu-panel">
      <h1><img src="/steam_assets/game-logo.png" alt="残明朱批：崇祯" /></h1>
      <p className="menu-subtitle">朕已知悉</p>
      {error && <p role="alert">{error}</p>}
      <nav aria-label="开局菜单">
        <button disabled={busy} onClick={() => void onAction({ action: 'new' })}>新开一局</button>
        <button disabled={busy} onClick={() => void onAction({ action: 'continue' })}>继续</button>
        <button disabled={busy} onClick={() => setPanel('saves')}>读取存档</button>
        <button disabled={busy} onClick={() => setPanel('settings')}>设置</button>
      </nav>
      {panel && <section className="menu-sheet">
        <button className="close" onClick={() => setPanel(null)}>关闭</button>
        {panel === 'settings' ? <SettingsForm initial={snapshot.settings} requiredSettings={snapshot.required_settings} onSave={settings => {
          void onAction({ action: 'settings', settings }).then(() => setPanel(null));
        }} /> : <><h2>读取存档</h2>{snapshot.saves.length === 0 && <p>没有存档</p>}
          {snapshot.saves.map(save => <button key={save} onClick={() => void onAction({ action: 'load', save })}>{save}</button>)}
        </>}
      </section>}
    </div>
  </main>;
}
