import React from 'react';
import type { Action, Settings, Snapshot } from '../types';

export function SettingsForm({ initial, onSave }: { initial: Settings; onSave: (settings: Settings) => void }) {
  const [value, setValue] = React.useState(initial);
  return <form className="settings" onSubmit={event => { event.preventDefault(); onSave(value); }}>
    <h2>设置</h2>
    <label>后端<select value={value.backend} onChange={event => setValue({ ...value, backend: event.target.value as Settings['backend'] })}>
      <option value="api">OpenAI 兼容 API</option><option value="claude-cli">Claude 命令行宿主</option><option value="codex">Codex 订阅</option><option value="grok">Grok 订阅</option><option value="pi">Pi 订阅</option>
    </select></label>
    <label>模型<input required={value.backend === 'api' || value.backend === 'codex'} value={value.model} onChange={event => setValue({ ...value, model: event.target.value })} /></label>
    {value.backend === 'api' && <>
      <label>API 地址<input required type="url" value={value.base_url} onChange={event => setValue({ ...value, base_url: event.target.value })} /></label>
      <label>API Key<input type="password" autoComplete="off" value={value.api_key} onChange={event => setValue({ ...value, api_key: event.target.value })} /></label>
    </>}
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
      {error && <p role="alert">{error}</p>}
      <nav aria-label="开局菜单">
        <button disabled={busy} onClick={() => void onAction({ action: 'new' })}>新开一局</button>
        <button disabled={busy} onClick={() => void onAction({ action: 'continue' })}>继续</button>
        <button disabled={busy} onClick={() => setPanel('saves')}>读取存档</button>
        <button disabled={busy} onClick={() => setPanel('settings')}>设置</button>
      </nav>
      {panel && <section className="menu-sheet">
        <button className="close" onClick={() => setPanel(null)}>关闭</button>
        {panel === 'settings' ? <SettingsForm initial={snapshot.settings} onSave={settings => {
          void onAction({ action: 'settings', settings }).then(() => setPanel(null));
        }} /> : <><h2>读取存档</h2>{snapshot.saves.length === 0 && <p>没有存档</p>}
          {snapshot.saves.map(save => <button key={save} onClick={() => void onAction({ action: 'load', save })}>{save}</button>)}
        </>}
      </section>}
    </div>
  </main>;
}
