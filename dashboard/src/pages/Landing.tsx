import {
  Activity,
  ArrowRight,
  Check,
  DatabaseZap,
  KeyRound,
  Layers,
  Moon,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  Undo2,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { currentTheme, setTheme } from "../lib/theme";
import { GATEWAY_URL } from "../lib/store";
import "./landing.css";

function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden>
      <rect width="20" height="20" rx="5" fill="var(--ink)" />
      <path
        d="M3 10h5M8 10l4-4h5M8 10h9M8 10l4 4h5"
        stroke="var(--on-ink)"
        strokeWidth="1.6"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

const FEATURES = [
  {
    icon: Zap,
    title: "Drop-in OpenAI API",
    body: "Change the base URL and the API key. Chat completions, streaming and model listing work with the OpenAI SDKs you already use.",
  },
  {
    icon: SlidersHorizontal,
    title: "Choose quality vs. cost",
    body: "Set quality to low, balanced or high for each request. LLMFlow picks the cheapest model that meets that level.",
  },
  {
    icon: Undo2,
    title: "Automatic fallback",
    body: "If a model is rate-limited or unavailable, LLMFlow retries the request on another suitable model, so your app keeps working.",
  },
  {
    icon: DatabaseZap,
    title: "Caching and spend limits",
    body: "Identical requests are answered from cache at no cost. Daily token and cost budgets and rate limits keep spending predictable.",
  },
  {
    icon: Activity,
    title: "Full visibility",
    body: "Every response states which model answered and why. The dashboard shows usage, latency, cost and routing for each request.",
  },
  {
    icon: KeyRound,
    title: "Your keys stay protected",
    body: "You use your own provider keys. They are verified when saved, encrypted at rest and in transit, and used only for your workspace.",
  },
];

const MEASURED = [
  { big: "-34%", label: "lower cost", detail: "Smaller 20B model vs. the 120B model on a 96-question mixed set: 89.6% vs. 99.0% correct" },
  { big: "-39%", label: "lower cost", detail: "Smaller model on 36 grade-school math problems (GSM8K), 97% correct" },
  { big: "-45%", label: "lower cost", detail: "Routing on the balanced setting across easy and medium questions, 100% correct" },
  { big: "$0", label: "per cached request", detail: "Repeated identical requests return the stored answer without calling a model" },
];

export function Landing() {
  const [theme, setThemeState] = useState(currentTheme);
  const endpoint = `${GATEWAY_URL}/v1`;

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  }

  return (
    <div className="lp">
      <a className="lp-skip" href="#main-content" onClick={(e) => { e.preventDefault(); scrollToId("main-content"); }}>
        Skip to content
      </a>

      <header className="lp-nav">
        <div className="lp-wrap lp-nav-inner">
          <a className="lp-brand" href="#/" aria-label="LLMFlow home">
            <Mark />
            LLMFlow
          </a>
          <nav className="lp-links" aria-label="Sections">
            <button className="lp-link" onClick={() => scrollToId("how")}>How it works</button>
            <button className="lp-link" onClick={() => scrollToId("features")}>Features</button>
            <button className="lp-link" onClick={() => scrollToId("results")}>Results</button>
            <button className="lp-link" onClick={() => scrollToId("security")}>Security</button>
          </nav>
          <div className="lp-nav-actions">
            <button
              className="btn ghost"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              {theme === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
            </button>
            <a className="btn ghost" href="#/signin">Sign in</a>
            <a className="btn primary" href="#/signup">Get started</a>
          </div>
        </div>
      </header>

      <main id="main-content">
        <section className="lp-wrap lp-hero" aria-labelledby="hero-title">
          <span className="lp-eyebrow"><i aria-hidden />Open source · MIT license</span>
          <h1 className="lp-h1" id="hero-title">Send every request to the right AI model.</h1>
          <p className="lp-sub">
            LLMFlow sits between your app and your AI providers. It sends each request to the
            cheapest model that can handle it, so you spend less without rewriting your code.
          </p>
          <div className="lp-cta">
            <a className="btn primary lg" href="#/signup">
              Create your workspace <ArrowRight size={16} aria-hidden />
            </a>
            <button className="btn lg" onClick={() => scrollToId("how")}>See how it works</button>
          </div>
          <div className="lp-trust">
            <span>Compatible with the OpenAI SDKs</span>
            <span>Uses your own provider keys</span>
            <span>Keys encrypted at rest and in transit</span>
            <span>Your data stays private</span>
          </div>

          <div className="lp-stage" style={{ marginTop: 64 }}>
            <figure className="lp-card" style={{ margin: 0 }}>
              <figcaption className="lp-card-head">
                <span className="lp-dots" aria-hidden><i /><i /><i /></span>
                <span>your app · python</span>
              </figcaption>
              <pre className="lp-code" aria-label="Example code">
{`from openai import OpenAI

client = OpenAI(
    `}<span className="c"># was https://api.openai.com/v1</span>{`
    base_url="`}<span className="k">{endpoint}</span>{`",
    api_key="llmf_…",
)

reply = client.chat.completions.create(
    model="`}<span className="k">auto</span>{`",
    messages=[{"role": "user", "content": "Hello!"}],
)`}
              </pre>
            </figure>

            <figure className="lp-card" style={{ margin: 0 }}>
              <figcaption className="lp-card-head">
                <span>response headers: which model answered, and why</span>
                <span>HTTP 200</span>
              </figcaption>
              <dl className="lp-kv" style={{ margin: 0 }}>
                <div><dt className="k">x-llmflow-provider</dt><dd className="v" style={{ margin: 0 }}>groq</dd></div>
                <div><dt className="k">x-llmflow-model</dt><dd className="v" style={{ margin: 0 }}><b>groq-gpt-oss-20b</b></dd></div>
                <div><dt className="k">x-llmflow-route-reason</dt><dd className="v" style={{ margin: 0 }}>difficulty=0.00 needs quality&gt;=0.30; cheapest eligible is groq-gpt-oss-20b</dd></div>
                <div><dt className="k">x-llmflow-attempts</dt><dd className="v" style={{ margin: 0 }}>1</dd></div>
                <div><dt className="k">x-llmflow-shadow-cost-usd</dt><dd className="v" style={{ margin: 0 }}>0.00001627</dd></div>
                <div><dt className="k">x-llmflow-cache</dt><dd className="v" style={{ margin: 0 }}>miss</dd></div>
              </dl>
            </figure>
          </div>
        </section>

        <section className="lp-section" id="how" aria-labelledby="how-title">
          <div className="lp-wrap">
            <div className="lp-kicker">How it works</div>
            <h2 className="lp-h2" id="how-title">Set up in three steps.</h2>
            <p className="lp-lede">
              You keep using the OpenAI SDK you already have. Only the base URL and the API key change.
            </p>
            <div className="lp-steps">
              <div className="lp-step">
                <div className="lp-num">01</div>
                <h3>Add your provider keys</h3>
                <p>Paste a key from your AI provider, such as Groq. LLMFlow checks it with the provider, stores it encrypted at rest and in transit, and shows it again only after you confirm your password.</p>
              </div>
              <div className="lp-step">
                <div className="lp-num">02</div>
                <h3>Connect your app</h3>
                <p>Replace the base URL with your LLMFlow address and use an LLMFlow API key. Set <code>model=&quot;auto&quot;</code> to let LLMFlow choose, or name a specific model.</p>
              </div>
              <div className="lp-step">
                <div className="lp-num">03</div>
                <h3>Route, cache and monitor</h3>
                <p>Each request goes to the cheapest model that meets your quality setting. Repeated requests are served from cache. The dashboard shows what was used and what it cost.</p>
              </div>
            </div>
          </div>
        </section>

        <section className="lp-section" id="features" aria-labelledby="features-title">
          <div className="lp-wrap">
            <div className="lp-kicker">Features</div>
            <h2 className="lp-h2" id="features-title">What LLMFlow does for you.</h2>
            <div className="lp-grid">
              {FEATURES.map((f) => (
                <article className="lp-feature" key={f.title}>
                  <f.icon size={22} strokeWidth={1.6} aria-hidden />
                  <h3>{f.title}</h3>
                  <p>{f.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-section" id="results" aria-labelledby="results-title">
          <div className="lp-wrap">
            <div className="lp-kicker">Results</div>
            <h2 className="lp-h2" id="results-title">Measured on real API calls.</h2>
            <p className="lp-lede">
              These figures come from the benchmark included in the repository. It sends real requests
              to Groq and checks every answer with code, not with another AI model. You can re-run it
              yourself with one command.
            </p>
            <div className="lp-measured">
              <table>
                <tbody>
                  <tr>
                    {MEASURED.map((m) => (
                      <td key={m.big} style={{ verticalAlign: "top" }}>
                        <div className="lp-big">{m.big}</div>
                        <div style={{ fontWeight: 500, marginTop: 2 }}>{m.label}</div>
                        <div className="muted" style={{ marginTop: 6, fontSize: 13, whiteSpace: "normal" }}>{m.detail}</div>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="lp-note">
              Costs are calculated from token usage at each model&apos;s published paid prices, so
              different strategies can be compared fairly (the free tier itself is not billed). The
              test sets are small, 36 to 96 questions, so treat the figures as indicative.
            </p>
          </div>
        </section>

        <section className="lp-section" id="security" aria-labelledby="security-title">
          <div className="lp-wrap">
            <div className="lp-kicker">Security</div>
            <h2 className="lp-h2" id="security-title">Built to protect your provider keys.</h2>
            <div className="lp-two">
              <p className="lp-lede" style={{ margin: 0 }}>
                Because LLMFlow stores your provider keys, security comes first. Secrets are encrypted
                or hashed, people and applications use separate credentials, and security-relevant
                actions are recorded in an audit log.
              </p>
              <ul className="lp-list">
                <li><ShieldCheck size={18} aria-hidden /><span><b>Encrypted provider keys.</b> Encrypted at rest and in transit, scoped to your workspace, and shown again only after you confirm your password.</span></li>
                <li><Layers size={18} aria-hidden /><span><b>Separate credentials.</b> People sign in with a password and optional two-factor authentication. Applications use API keys that you can revoke and that cannot change workspace settings.</span></li>
                <li><Check size={18} aria-hidden /><span><b>Protected accounts.</b> Passwords are hashed with argon2id, repeated failed sign-ins lock the account temporarily, and one-time recovery codes are provided.</span></li>
                <li><Check size={18} aria-hidden /><span><b>Your data stays private.</b> LLMFlow never stores your prompts or responses. The request log keeps only metadata: model, token counts, latency and cost.</span></li>
              </ul>
            </div>
          </div>
        </section>

        <section className="lp-final" aria-labelledby="cta-title">
          <div className="lp-wrap">
            <h2 className="lp-h2" id="cta-title">Get started in minutes.</h2>
            <p className="lp-lede" style={{ margin: "18px auto 0" }}>
              Create a workspace, add a provider key, and send your first request.
            </p>
            <div className="lp-cta">
              <a className="btn primary lg" href="#/signup">Create your workspace <ArrowRight size={16} aria-hidden /></a>
              <a className="btn lg" href="#/signin">Sign in</a>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-foot">
        <div className="lp-wrap lp-foot-inner">
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
            <Mark size={18} /> LLMFlow · MIT License
          </span>
          <span>Provider keys are encrypted at rest and in transit. Your prompts and responses stay private.</span>
        </div>
      </footer>
    </div>
  );
}
