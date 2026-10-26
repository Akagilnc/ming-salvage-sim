import { MarkdownText } from './markdownText';
import type { Turn } from '../types';

interface Block { speaker: string; text: string }

// These are the explicit scene display markers, not inferred prose semantics.
export function sceneBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const line of text.split('\n')) {
    const end = line.startsWith('【') ? line.indexOf('】') : -1;
    if (end > 0) blocks.push({ speaker: line.slice(1, end), text: line.slice(end + 1) });
    else if (blocks.length) blocks[blocks.length - 1].text += '\n' + line;
    else blocks.push({ speaker: '', text: line });
  }
  return blocks;
}

export function currentSpeaker(turns: Turn[], live: string, hall: string[]): string {
  let speaker = '';
  for (const text of [...turns.map(turn => turn.scene), live]) {
    for (const block of sceneBlocks(text)) {
      if (hall.includes(block.speaker) && block.speaker !== '王承恩') speaker = block.speaker;
    }
  }
  return speaker;
}

export function Scene({ text }: { text: string }) {
  return <>{sceneBlocks(text).map((block, index) => {
    const aside = block.speaker === '王承恩·低语';
    const kind = aside ? 'aside' : block.speaker === '旁白' ? 'narration' : block.speaker === '旨' ? 'decree' : 'speech';
    return <section key={index} className={`scene-block ${kind}`}>
      {block.speaker.startsWith('王承恩') && <img className="attendant-avatar" src="/portraits/minister_王承恩.png" alt="王承恩" />}
      <header><MarkdownText>{block.speaker}</MarkdownText></header><MarkdownText>{block.text}</MarkdownText>
    </section>;
  })}</>;
}

export function ScrollMessages({ turns }: { turns: Turn[] }) {
  return <>{turns.map(turn => <article className="audience-turn" key={turn.id}>
    <div className="emperor"><small>朕</small><MarkdownText>{turn.emperor_words}</MarkdownText></div>
    <Scene text={turn.scene} />
  </article>)}</>;
}
