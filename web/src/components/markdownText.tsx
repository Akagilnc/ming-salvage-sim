import Markdown from 'react-markdown';
import remarkCjkFriendly from 'remark-cjk-friendly';

export function MarkdownText({ children }: { children: string }) {
  return <Markdown remarkPlugins={[remarkCjkFriendly]}>{children}</Markdown>;
}
