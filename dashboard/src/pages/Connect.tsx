import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Gate } from "../components/Gate";
import { PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { buildSnippets } from "../lib/snippets";
import { useConnection } from "../lib/store";
import { useAsync } from "../lib/useAsync";

function CopyBlock({ title, code }: { title: string; code: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable: the text is still selectable */
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2 className="section-title">{title}</h2>
        <button className="btn ghost" onClick={() => void copy()} aria-label={`Copy ${title}`}>
          {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="codeblock" style={{ margin: 16, width: "auto" }}>
        {code}
      </pre>
    </section>
  );
}

function Body() {
  const { conn } = useConnection();
  const models = useAsync(async () => (await api.account(conn)).models, [conn]);
  const enabled = models.data?.filter((m) => m.enabled) ?? [];

  return (
    <>
      <PageHeader
        title="Connect your app"
        description="LLMFlow speaks the OpenAI API. Point your app at it and change nothing else."
      />

      <section className="panel panel-body stack">
        <h2 className="section-title">How it works</h2>
        <ol className="steps">
          <li>
            <b>Gateway URL</b>: <code>{conn.baseUrl}/v1</code>. Use this as the base URL instead of
            api.openai.com.
          </li>
          <li>
            <b>API key</b>: one of your workspace&apos;s keys (see <a href="#/keys">API keys</a>). It is
            different from your login, and your provider keys stay encrypted on the gateway.
          </li>
          <li>
            <b>Model</b>: use <code>auto</code> to let LLMFlow route each request, or pin one of the models
            below.
          </li>
        </ol>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2 className="section-title">Models you can request</h2>
        </div>
        <div className="panel-body">
          <div className="legend" style={{ gap: 8 }}>
            <span className="badge">auto</span>
            {enabled.map((m) => (
              <span className="badge mono" key={m.id}>
                {m.id}
              </span>
            ))}
            {models.data && enabled.length === 0 && (
              <span className="muted">
                Add a provider key under Providers to enable models.
              </span>
            )}
          </div>
        </div>
      </section>

      {buildSnippets(conn.baseUrl).map((s) => (
        <CopyBlock key={s.id} title={s.title} code={s.code} />
      ))}

      <section className="panel panel-body stack">
        <h2 className="section-title">Per-request options</h2>
        <p className="muted">
          Pass an <code>llmflow</code> object in the request body (<code>extra_body</code> in the Python SDK).
        </p>
        <dl className="kv">
          <dt>quality</dt>
          <dd>low · balanced · high</dd>
          <dt>privacy</dt>
          <dd>standard · strict (skip providers that train on prompts)</dd>
          <dt>fallback</dt>
          <dd>true · false</dd>
          <dt>cache</dt>
          <dd>auto · on · off</dd>
        </dl>
      </section>
    </>
  );
}

export function Connect() {
  return (
    <div className="page">
      <Gate>
        <Body />
      </Gate>
    </div>
  );
}
