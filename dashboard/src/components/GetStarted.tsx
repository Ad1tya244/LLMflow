import { Check } from "lucide-react";
import { api } from "../lib/api";
import { useConnection } from "../lib/store";
import { useAsync } from "../lib/useAsync";

interface Step {
  done: boolean;
  title: string;
  body: string;
  href: string;
  action: string;
}

export function GetStarted() {
  const { conn } = useConnection();
  const { data } = useAsync(async () => {
    const [account, keys, requests] = await Promise.all([
      api.account(conn),
      api.apiKeys(conn),
      api.requests(conn, 1, 0),
    ]);
    return {
      hasProvider: account.providers.some((p) => p.configured),
      hasKey: keys.keys.some((k) => k.revoked_at === null),
      hasRequest: requests.total > 0,
    };
  }, [conn]);

  if (!data) return null;
  const steps: Step[] = [
    {
      done: data.hasProvider,
      title: "Add a provider key",
      body: "Connect your own Groq key so LLMFlow has models to route to.",
      href: "#/providers",
      action: "Add key",
    },
    {
      done: data.hasKey,
      title: "Create an API key",
      body: "Your apps use this key instead of the provider key.",
      href: "#/keys",
      action: "Create key",
    },
    {
      done: data.hasRequest,
      title: "Send your first request",
      body: "Try the Playground, or copy a snippet from Connect into your app.",
      href: "#/playground",
      action: "Open Playground",
    },
  ];
  if (steps.every((s) => s.done)) return null;
  const doneCount = steps.filter((s) => s.done).length;

  return (
    <section className="panel get-started" aria-label="Getting started">
      <div className="panel-head">
        <h2 className="section-title">Get started</h2>
        <span className="section-note">
          {doneCount} of {steps.length} done
        </span>
      </div>
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={s.title} className={s.done ? "done" : undefined}>
            <span className="step-mark" aria-hidden>
              {s.done ? <Check size={14} strokeWidth={2.4} /> : i + 1}
            </span>
            <span className="step-text">
              <b>{s.title}</b>
              <span className="muted">{s.body}</span>
            </span>
            {s.done ? (
              <span className="badge good">Done</span>
            ) : (
              <a className="btn" href={s.href}>
                {s.action}
              </a>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
