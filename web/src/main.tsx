import React from 'react';
import { createRoot } from 'react-dom/client';
import { act, records, state } from './api';
import { MenuPage, SettingsForm } from './components/menuPage';
import { currentSpeaker, Scene, ScrollMessages } from './components/scrollMessages';
import type { Action, Records, Snapshot } from './types';
import './styles.css';

export function App() {
  const [snapshot, setSnapshot] = React.useState<Snapshot | null>(null);
  const [book, setBook] = React.useState<Records>({ entities: [], facts: [] });
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [live, setLive] = React.useState('');
  const [liveGazette, setLiveGazette] = React.useState('');
  const [reading, setReading] = React.useState<number | 'latest' | null>('latest');
  const gazetteStreaming = React.useRef(false);
  const choosingNow = React.useRef(new Set<string>());
  const [choosing, setChoosing] = React.useState<Set<string>>(new Set());
  const [pendingWords, setPendingWords] = React.useState('');
  const [input, setInput] = React.useState('');
  const [panel, setPanel] = React.useState<'roster' | 'orders' | 'history' | 'settings' | null>(null);
  const scroll = React.useRef<HTMLDivElement>(null);
  const follow = React.useRef(true);

  const refresh = React.useCallback(async (next?: Snapshot) => {
    const value = next ?? await state();
    setSnapshot(value);
    if (value.save) setBook(await records());
    if (!value.game?.running) { setLive(''); setPendingWords(''); setLiveGazette(''); }
  }, []);

  React.useEffect(() => {
    void refresh().catch(reason => setError(String(reason)));
    const events = new EventSource('/stream');
    events.addEventListener('delta', event => {
      const chunk = JSON.parse((event as MessageEvent).data) as { text: string; hall: string[] };
      setLive(text => text + chunk.text);
      setSnapshot(value => value?.game?.night ? {
        ...value, game: { ...value.game, night: { ...value.game.night, hall: chunk.hall } },
      } : value);
    });
    events.addEventListener('gazette', event => {
      if (!gazetteStreaming.current) { setReading('latest'); setLiveGazette(''); }
      gazetteStreaming.current = true;
      setLiveGazette(text => text + (JSON.parse((event as MessageEvent).data) as string));
    });
    const receive = (event: Event) => {
      if (event.type === 'done') gazetteStreaming.current = false;
      void refresh(JSON.parse((event as MessageEvent).data)).catch(reason => setError(String(reason)));
    };
    events.addEventListener('state', receive);
    events.addEventListener('done', receive);
    return () => events.close();
  }, [refresh]);

  React.useLayoutEffect(() => {
    if (follow.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [live, snapshot?.game?.night?.turns.length]);

  async function action(value: Action) {
    setError('');
    if (value.action === 'choose' && value.petition) {
      if (choosingNow.current.has(value.petition)) return;
      choosingNow.current.add(value.petition);
      setChoosing(new Set(choosingNow.current));
    }
    else if (value.action !== 'dismiss') setBusy(true);
    if (value.action === 'say') { setPendingWords(value.words ?? ''); setLive(''); follow.current = true; }
    try {
      if (await act(value) === 200 || value.action === 'choose') await refresh();
      if (value.action === 'open') follow.current = true;
      if (value.action === 'new' || value.action === 'continue' || value.action === 'load') { setPanel(null); setReading('latest'); }
    } catch (reason) { setError(String(reason)); }
    finally {
      if (value.action === 'choose') {
        choosingNow.current.delete(value.petition!);
        setChoosing(new Set(choosingNow.current));
      }
      else if (value.action !== 'dismiss') setBusy(false);
    }
  }

  if (!snapshot) return <main className="loading">{error || '正在打开…'}</main>;
  if (!snapshot.game) return <MenuPage snapshot={snapshot} onAction={action} busy={busy} error={error} />;

  const game = snapshot.game;
  const night = game.night;
  const audience = game.face === 'audience';
  const turns = night?.turns ?? [];
  const speaker = currentSpeaker(turns, live, night?.hall ?? []);
  const people = book.entities.filter(entity => entity.kind === 'person');
  const gazettes = [
    ...book.entities.filter(entity => entity.kind === 'gazette').map(entity => String(entity.data.text ?? '')),
    ...book.facts.filter(fact => fact.kind === 'gazette').map(fact => String(fact.detail.text ?? '')),
  ];
  const gazette = reading === 'latest' ? (liveGazette || gazettes.at(-1))
    : reading === null ? null : gazettes[reading];
  const pending = game.pending?.payload.words || pendingWords || game.failure?.payload.words;
  const failure = game.failure && <div className="system-failure" role="alert">
    此处未能完成。{game.failure.payload.log && <>错误记录：<code>{game.failure.payload.log}</code>，请把它发给作者。</>}
    <button disabled={busy || game.running} onClick={() => void action({ action: 'retry' })}>重试</button>
  </div>;

  return <main className={`game ${audience ? 'audience' : 'desk'}`}>
    <header className="topbar">
      <h1>残明朱批</h1><span>{game.date.year} 年 {game.date.month} 月</span>
      <nav><button onClick={() => setPanel(panel === 'roster' ? null : 'roster')}>名册</button>
        <button onClick={() => setPanel(panel === 'orders' ? null : 'orders')}>案头</button>
        <button onClick={() => setPanel(panel === 'history' ? null : 'history')}>起居录</button>
        <button onClick={() => setPanel(panel === 'settings' ? null : 'settings')}>设置</button>
      </nav>
      {audience ? <button onClick={() => void action({ action: 'dismiss' })}>退朝</button>
        : <button disabled={busy || game.running || game.face === 'month'} onClick={() => void action({ action: 'open' })}>召对</button>}
    </header>
    {error && <p role="alert" className="request-error">{error}</p>}
    <div className="court-layout">
      {audience && <aside className="portrait">
        {speaker && <><img src={`/portraits/minister_${encodeURIComponent(speaker)}.png`} alt={speaker} /><h2>{speaker}</h2></>}
        <img className="attendant-avatar" src="/portraits/minister_王承恩.png" alt="王承恩" />
      </aside>}
      <section className="paper">
        <div className="scroll" ref={scroll} onScroll={() => {
          const element = scroll.current;
          if (element) follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 70;
        }}>
          {audience ? <>
            <ScrollMessages turns={turns} />
            {pending && <p className="emperor"><small>朕</small>{pending}</p>}
            {live && <Scene text={live} />}
            {failure}
          </> : <>
            <h2>{game.face === 'month' ? '核账期' : '案头'}</h2>
            {failure}
          </>}
          {reading !== null && (!audience || typeof reading === 'number') && <article className="gazette">
            <h2>邸报</h2><div>{gazette}</div>
            <button onClick={() => setReading(null)}>朕知道了</button>
          </article>}
          {!audience && night?.result === 'unhandled' && <p className="unhandled">接不住</p>}
          {!audience && book.facts.filter(fact => fact.kind === 'unhandled' && !book.entities.some(entity => entity.id === fact.entity_id && entity.kind === 'night')).map((fact, index) => <p key={`${fact.entity_id}-${index}`} className="unhandled">接不住</p>)}
          {game.petitions.map(petition => <article className="petition" key={petition.id}>
            <h3>奏疏{petition.signer && ` · ${petition.signer}`}</h3>
            {petition.target && <p>被劾人：{petition.target}</p>}
            {petition.revision_of && <small>改票</small>}
            <p>{petition.text}</p>
            {petition.options.map((option, index) => <button disabled={choosing.has(petition.id)} key={index} onClick={() => void action({ action: 'choose', petition: petition.id, option: index })}>{option}</button>)}
          </article>)}
          {game.returned_petitions.map(({ petition, awaiting_drafter }) => <article className="petition" key={petition.id}>
            <h3>待改票 · {petition.signer}</h3><p>{petition.text}</p>
            <small>{awaiting_drafter ? '无人改票，待补任后再呈' : '已发回，待改票再呈'}</small>
          </article>)}
        </div>
        {audience ? <form className="composer" onSubmit={event => {
          event.preventDefault(); if (!input.trim()) return;
          const words = input; setInput(''); void action({ action: 'say', words });
        }}>
          <label htmlFor="emperor-words">朕谕</label><textarea id="emperor-words" value={input} onChange={event => setInput(event.target.value)} disabled={busy || game.running} />
          <button disabled={busy || game.running || !input.trim()}>发送</button>
        </form> : <footer className="desk-actions"><button disabled={busy || game.running} onClick={() => void action({ action: 'month' })}>过月</button></footer>}
      </section>
      {panel && <aside className="drawer">
        <button className="close" onClick={() => setPanel(null)}>合上</button>
        {panel === 'settings' ? <SettingsForm initial={snapshot.settings} onSave={settings => { void action({ action: 'settings', settings }).then(() => setPanel(null)); }} /> :
          panel === 'roster' ? <><h2>名册</h2>{people.map(person => <article key={person.id}>
            <h3>{person.key}</h3><p>{String(person.data.office ?? '')} · {String(person.data.location ?? '')} · {String(person.data.status ?? '')}</p>
            {audience && <button disabled={busy || game.running} onClick={() => void action({ action: 'say', words: `宣${person.key}。` })}>宣召</button>}
          </article>)}</> : panel === 'orders' ? <><h2>旨意去向</h2>{book.entities.filter(entity => entity.kind === 'decree').map(entity => <article key={entity.id}>
            <p>{String(entity.data.text)}</p><small>{String(entity.data.origin)} · {String(entity.data.people)}</small>
          </article>)}</> : <><h2>起居录</h2>{book.entities.filter(entity => entity.kind === 'night').map(entity => <details key={entity.id}>
            <summary>{entity.key}</summary><ScrollMessages turns={(entity.data as unknown as NonNullable<typeof night>).turns} />
            {entity.data.result === 'unhandled' && <p className="unhandled">接不住</p>}
          </details>)}<h2>历期邸报</h2>{gazettes.map((_text, index) => <button key={index} onClick={() => { setReading(index); setPanel(null); }}>第 {index + 1} 期</button>)}</>}
      </aside>}
    </div>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App />);
