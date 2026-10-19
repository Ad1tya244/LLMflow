import "katex/dist/katex.min.css";
import { Check, Copy } from "lucide-react";
import { isValidElement, useState, type ReactElement, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

/** Renders model output the way chat products do: headings, lists, tables, quotes, code blocks
 *  with a copy button, links, and LaTeX math. Raw HTML in the reply is shown as text, never
 *  rendered, and unsafe link schemes (``javascript:``) are dropped by react-markdown. */

// Models write math as \( … \) and \[ … \]; the Markdown math plugin expects $$ … $$.
// Code is left untouched so a backslash in a snippet is never rewritten.
export function normaliseMath(source: string): string {
  const parts = source.split(/(```[\s\S]*?(?:```|$)|`[^`\n]+`)/g);
  return parts
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part
            .replace(/\\\[([\s\S]+?)\\\]/g, (_m, body: string) => `\n\n$$\n${body.trim()}\n$$\n\n`)
            .replace(/\\\(([\s\S]+?)\\\)/g, (_m, body: string) => `$$${body.trim()}$$`)
            // Models also write inline math as $...$. That is only read as math when it holds a
            // LaTeX command (\frac, \times, ...), so "$5 and $10" stays plain currency text.
            .replace(
              /(?<![\\$])\$([^$\n]*\\[a-zA-Z][^$\n]*)\$(?!\$)/g,
              (_m, body: string) => `$$${body.trim()}$$`,
            ),
    )
    .join("");
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = isValidElement(children)
    ? (children as ReactElement<{ className?: string; children?: ReactNode }>)
    : null;
  const text = String(code?.props.children ?? "").replace(/\n$/, "");
  const language = /language-([\w+-]+)/.exec(code?.props.className ?? "")?.[1];

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable: the code is still selectable */
    }
  }

  return (
    <div className="md-codeblock">
      <div className="md-codebar">
        <span>{language ?? "text"}</span>
        <button type="button" className="md-copy" onClick={() => void copy()} aria-label="Copy code">
          {copied ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  );
}

const components: Components = {
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="md-table">
      <table>{children}</table>
    </div>
  ),
};

export function Markdown({ source }: { source: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore" }]]}
        components={components}
      >
        {normaliseMath(source)}
      </ReactMarkdown>
    </div>
  );
}
