import React from 'react';
import { createRoot } from 'react-dom/client';
import { act, records, state } from './api';
import { MenuPage, SettingsForm } from './components/menuPage';
import { MarkdownText } from './components/markdownText';
import { currentSpeaker, Scene, ScrollMessages } from './components/scrollMessages';
import type { Action, Records, Snapshot, TextUpdate } from './types';
import './styles.css';

export function App() {
  const [snapshot, setSnapshot] = React.useState<Snapshot | null>(null);
  const [book, setBook] = React.useState<Records>({ entities: [], facts: [] });
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [live, setLive] = React.useState('');
  const [liveGazette, setLiveGazette] = React.useState('');
  const [reading, setReading] = React.useState<number | 'latest' | null>(null);
  const gazetteStreaming = React.useRef(false);
  const previous = React.useRef<Snapshot | null>(null);
  const refreshing = React.useRef(0);
  const choosingNow = React.useRef(new Set<string>());
  const [choosing, setChoosing] = React.useState<Set<string>>(new Set());
  const [pendingWords, setPendingWords] = React.useState('');
  const [input, setInput] = React.useState('');
  const [panel, setPanel] = React.useState<'roster' | 'orders' | 'history' | 'settings' | null>(null);
  const scroll = React.useRef<HTMLDivElement>(null);
  const follow = React.useRef(true);

  const refresh = React.useCallback(async (next?: Snapshot) => {
    const request = ++refreshing.current;
    const value = next ?? await state();
    const contents = value.save ? await records() : { entities: [], facts: [] };
    if (request !== refreshing.current) return;
    const before = previous.current;
    if (before?.save === value.save && before?.game && value.game
      && (before.game.date.year !== value.game.date.year || before.game.date.month !== value.game.date.month)) {
      setReading('latest'); setPanel(null);
    }
    previous.current = value;
    setBook(contents);
    setSnapshot(value);
    if (!value.game?.running) { setLive(''); setPendingWords(''); setLiveGazette(''); }
  }, []);

  React.useEffect(() => {
    void refresh().catch(reason => setError(String(reason)));
    const events = new EventSource('/stream');
    events.addEventListener('delta', event => {
      const chunk = JSON.parse((event as MessageEvent).data) as { text: TextUpdate; hall: string[] };
      setLive(text => typeof chunk.text === 'string' ? text + chunk.text : chunk.text.replace);
      setSnapshot(value => value?.game?.night ? {
        ...value, game: { ...value.game, night: { ...value.game.night, hall: chunk.hall } },
      } : value);
    });
    events.addEventListener('gazette', event => {
      if (!gazetteStreaming.current) setLiveGazette('');
      gazetteStreaming.current = true;
      const chunk = JSON.parse((event as MessageEvent).data) as TextUpdate;
      setLiveGazette(text => typeof chunk === 'string' ? text + chunk : chunk.replace);
    });
    const receive = (event: Event) => {
      const next = JSON.parse((event as MessageEvent).data) as Snapshot;
      if (next.game?.face !== 'month' || next.game.failure) gazetteStreaming.current = false;
      void refresh(next).catch(reason => setError(String(reason)));
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
      if (value.action === 'new' || value.action === 'continue' || value.action === 'load') { setPanel(null); setReading(value.action === 'new' ? 'latest' : null); }
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
  const gazetteRecords = [
    ...book.entities.filter(entity => entity.kind === 'gazette').map(entity => entity.data),
    ...book.facts.filter(fact => fact.kind === 'gazette').map(fact => fact.detail),
  ];
  const gazettes = gazetteRecords.map(record => String(record.text ?? ''));
  const monthGazette = String(gazetteRecords.find(record => {
    const date = record.date as typeof game.date | undefined;
    return date?.year === game.date.year && date.month === game.date.month;
  })?.text ?? liveGazette);
  const gazette = reading === 'latest' ? (liveGazette || gazettes.at(-1))
    : reading === null ? null : gazettes[reading];
  const pending = game.pending?.payload.words || pendingWords || game.failure?.payload.words;
  const failure = game.failure && <div className="system-failure" role="alert">
    此处未能完成。{game.failure.payload.log && <>错误记录：<code>{game.failure.payload.log}</code>，请把它发给作者。</>}
    <button disabled={busy || game.running} onClick={() => void action({ action: 'retry' })}>重试</button>
  </div>;

  if (game.face !== 'month' && reading !== null && gazette != null) return <main className="game desk">
    <header className="topbar"><h1>残明朱批</h1><span>{game.date.year} 年 {game.date.month} 月</span></header>
    <div className="court-layout"><section className="paper"><div className="scroll">
      <article className="gazette"><h2>邸报</h2><MarkdownText>{gazette}</MarkdownText>
        <button onClick={() => setReading(null)}>朕已知悉</button>
      </article>
    </div></section></div>
  </main>;

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
        {game.face === 'desk' && game.unhandled_monthly.map(item => <div key={item.entity_id} className="unhandled" role="status">
          本月接不住
        </div>)}
        <div className="scroll" ref={scroll} onScroll={() => {
          const element = scroll.current;
          if (element) follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 70;
        }}>
          {audience ? <>
            <ScrollMessages turns={turns} />
            {pending && <div className="emperor"><small>朕</small><MarkdownText>{pending}</MarkdownText></div>}
            {live && <Scene text={live} />}
            {failure}
          </> : <>
            <h2>{game.face === 'month' && !game.petitions.some(p => p.blocking) ? '核账期' : '案头'}</h2>
            {failure}
            {game.face === 'month' && game.running && !game.petitions.length && !monthGazette && !failure && <p role="status">正在过月，请稍候。</p>}
          </>}
          {game.face === 'month' && monthGazette && <article className="gazette">
            <h2>邸报</h2><MarkdownText>{monthGazette}</MarkdownText>
          </article>}
          {!audience && night?.result === 'unhandled' && <p className="unhandled">接不住</p>}
          {game.petitions.map(petition => <article className="petition" key={petition.id}>
            <header>奏疏{petition.signer && <MarkdownText>{petition.signer}</MarkdownText>}</header>
            {petition.target && <MarkdownText>{`被劾人：${petition.target}`}</MarkdownText>}
            {petition.revision_of && <small>改票</small>}
            <MarkdownText>{petition.text}</MarkdownText>
            {petition.options.map((option, index) => <button disabled={choosing.has(petition.id)} key={index} onClick={() => void action({ action: 'choose', petition: petition.id, option: index })}><MarkdownText>{option}</MarkdownText></button>)}
          </article>)}
          {game.returned_petitions.map(({ petition, awaiting_drafter }) => <article className="petition" key={petition.id}>
            <header>待改票<MarkdownText>{petition.signer ?? ''}</MarkdownText></header><MarkdownText>{petition.text}</MarkdownText>
            <small>{awaiting_drafter ? '无人改票，待补任后再呈' : '已发回，待改票再呈'}</small>
          </article>)}
        </div>
        {audience ? <form className="composer" onSubmit={event => {
          event.preventDefault(); if (!input.trim()) return;
          const words = input; setInput(''); void action({ action: 'say', words });
        }}>
          <label htmlFor="emperor-words">朕谕</label><textarea id="emperor-words" value={input} onChange={event => setInput(event.target.value)} disabled={busy || game.running} onKeyDown={event => {
            if (event.key === 'Enter' && event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
              event.preventDefault(); event.currentTarget.form?.requestSubmit();
            }
          }} />
          <button disabled={busy || game.running || !input.trim()}>发送</button>
        </form> : <footer className="desk-actions"><button disabled={busy || game.running} onClick={() => void action({ action: 'month' })}>过月</button></footer>}
      </section>
      {panel && <aside className="drawer">
        <button className="close" onClick={() => setPanel(null)}>合上</button>
        {panel === 'settings' ? <SettingsForm initial={snapshot.settings} requiredSettings={snapshot.required_settings} onSave={settings => { void action({ action: 'settings', settings }).then(() => setPanel(null)); }} /> :
          panel === 'roster' ? <><h2>名册</h2>{people.map(person => <article key={person.id}>
            <header><MarkdownText>{person.key}</MarkdownText></header><MarkdownText>{`${((person.data.appointments ?? []) as { office: string; territory: string; role: string }[]).map(a => `${a.role === 'acting' ? '署' : ''}${a.territory}${a.office}`).join('、') || String(person.data.identity_description ?? '')} · ${String(person.data.location ?? '')} · ${String(person.data.status ?? '')}`}</MarkdownText>
            {audience && <button disabled={busy || game.running} onClick={() => void action({ action: 'say', words: `宣${person.key}。` })}>宣召</button>}
          </article>)}</> : panel === 'orders' ? <><h2>旨意去向</h2>{book.entities.filter(entity => entity.kind === 'decree').map(entity => <article key={entity.id}>
            <MarkdownText>{String(entity.data.text)}</MarkdownText><MarkdownText>{`${String(entity.data.origin)} · ${String(entity.data.people)}`}</MarkdownText>
            {book.facts.filter(fact => fact.entity_id === entity.id && fact.kind === 'secret_report').map((fact, index) => <details className="gazette" key={index}>
              <summary>密报 · {String((fact.detail.date as { year: number; month: number }).year)} 年 {String((fact.detail.date as { year: number; month: number }).month)} 月</summary>
              <MarkdownText>{String(fact.detail.text)}</MarkdownText>
            </details>)}
          </article>)}</> : <><h2>起居录</h2>{book.entities.filter(entity => entity.kind === 'night').map(entity => <details key={entity.id}>
            <summary><MarkdownText>{entity.key}</MarkdownText></summary><ScrollMessages turns={(entity.data as unknown as NonNullable<typeof night>).turns} />
            {entity.data.result === 'unhandled' && <p className="unhandled">接不住</p>}
          </details>)}<h2>历期邸报</h2>{gazettes.map((_text, index) => <button key={index} onClick={() => { setReading(index); setPanel(null); }}>第 {index + 1} 期</button>)}</>}
      </aside>}
    </div>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App />);
