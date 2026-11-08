import Markdown from 'react-markdown';
import remarkCjkFriendly from 'remark-cjk-friendly';
import remend from 'remend';

export function MarkdownText({ children, streaming = false }: { children: string; streaming?: boolean }) {
  return <Markdown remarkPlugins={[remarkCjkFriendly]}>{streaming ? remend(children) : children}</Markdown>;
}
