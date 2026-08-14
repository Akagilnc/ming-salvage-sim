import MarkdownIt from "markdown-it";

const markdown = new MarkdownIt({ html: false, linkify: false, typographer: false });
const markdownBacktickRule = markdown.inline.ruler.__rules__.find((rule) => rule.name === "backticks")?.fn;
if (!markdownBacktickRule) throw new Error("markdown-it backticks rule is unavailable");

markdown.inline.ruler.at("backticks", (state, silent) => {
  const start = state.pos;
  const tokenCount = state.tokens.length;
  const parsed = markdownBacktickRule(state, silent);
  if (!parsed || silent) return parsed;
  const token = state.tokens.slice(tokenCount).find((candidate) => candidate.type === "code_inline");
  if (token) {
    const contentStart = start + token.markup.length;
    const contentEnd = state.pos - token.markup.length;
    token.meta = { ...token.meta, literalContent: state.src.slice(contentStart, contentEnd) };
  }
  return parsed;
});

const inlineText = (tokens) => tokens.map((token) => {
  switch (token.type) {
    case "text":
    case "html_inline": return token.content;
    case "code_inline": return token.meta?.literalContent ?? token.content;
    case "image": return inlineText(token.children || []);
    case "softbreak":
    case "hardbreak": return "\n";
    default: return "";
  }
}).join("");

const appendBlockSeparator = (result, previousEndLine, startLine) =>
  previousEndLine === undefined || startLine === undefined
    ? result
    : result + "\n".repeat(Math.max(1, startLine - previousEndLine + 1));

export const stripOrganicMarkdown = (text) => {
  const tokens = markdown.parse(text, {});
  let result = "";
  let previousEndLine;
  let tableEndLine;
  for (const token of tokens) {
    const [startLine, endLine] = token.map || [];
    switch (token.type) {
      case "inline":
        result = appendBlockSeparator(result, previousEndLine, startLine);
        result += inlineText(token.children || []);
        if (endLine !== undefined) previousEndLine = endLine;
        break;
      case "fence":
      case "code_block":
      case "html_block":
        result = appendBlockSeparator(result, previousEndLine, startLine) + token.content;
        if (endLine !== undefined) previousEndLine = endLine;
        break;
      case "hr": if (endLine !== undefined) previousEndLine = endLine; break;
      case "table_open":
        result = appendBlockSeparator(result, previousEndLine, startLine);
        tableEndLine = endLine;
        break;
      case "td_close":
      case "th_close": result += "\t"; break;
      case "tr_close": result = result.replace(/\t$/, "") + "\n"; break;
      case "table_close":
        result = result.replace(/\n$/, "");
        previousEndLine = tableEndLine;
        tableEndLine = undefined;
        break;
      default: break;
    }
  }
  return result;
};

export const filterMatchedHighlights = (answer, highlights) => {
  const display = stripOrganicMarkdown(answer || "");
  return (highlights || []).map((raw) => stripOrganicMarkdown(String(raw || "")))
    .filter((phrase) => phrase && display.includes(phrase));
};
