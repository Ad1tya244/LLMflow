#!/usr/bin/env node
// One-command demo: starts the whole stack (installing anything missing on first run), then
// uses the official OpenAI SDK to talk to the gateway and prints what happened.
//   npm run demo           run the demo, then keep the stack up so you can explore the dashboard
//   npm run demo -- --once run the demo and exit
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const win = process.platform === "win32";
const py = join(backend, ".venv", win ? "Scripts" : "bin", win ? "python.exe" : "python");
const once = process.argv.includes("--once");
const API = `http://localhost:${process.env.LLMFLOW_PORT ?? "8000"}`;
const WEB = `http://localhost:${process.env.LLMFLOW_WEB_PORT ?? "5173"}`;

const log = (m) => console.log(`\x1b[2m[demo]\x1b[0m ${m}`);

function readEnv() {
  const f = join(backend, ".env");
  const out = {};
  if (existsSync(f)) {
    for (const l of readFileSync(f, "utf8").split(/\r?\n/)) {
      const m = l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
      if (m) out[m[1]] = m[2].replace(/^['"]|['"]$/g, "");
    }
  }
  return out;
}

async function up() {
  try {
    return (await fetch(`${API}/healthz`)).ok;
  } catch {
    return false;
  }
}

let stack = null;
let started = false;
function stop(code = 0) {
  if (stack && started) stack.kill("SIGINT");
  setTimeout(() => process.exit(code), 800).unref();
}
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));

if (!(await up())) {
  log("starting LLMFlow (first run installs dependencies and can take a minute or two)...");
  stack = spawn("node", [join(root, "scripts", "dev.mjs")], { cwd: root, stdio: "ignore" });
  started = true;
  stack.on("exit", (c) => {
    if (c) {
      console.error(`\x1b[31m[demo]\x1b[0m the stack exited with code ${c}; run 'npm run dev' to see why`);
      process.exit(1);
    }
  });
  const deadline = Date.now() + 5 * 60_000;
  while (!(await up())) {
    if (Date.now() > deadline) {
      console.error("timed out waiting for the API");
      stop(1);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
} else {
  log("LLMFlow is already running; reusing it");
}

const env = readEnv();
const key = (env.LLMFLOW_API_KEYS ?? "").split(",")[0]?.trim();
if (!key) {
  console.error("No LLMFLOW_API_KEYS in backend/.env");
  stop(1);
}
if (!(env.GROQ_API_KEY ?? "").trim()) {
  console.error(
    "\nGROQ_API_KEY is empty in backend/.env. Get a free key at https://console.groq.com,\n" +
      "paste it after GROQ_API_KEY=, save, and run this again.",
  );
  stop(1);
}

const have = spawnSync(py, ["-c", "import openai"], { stdio: "ignore" });
if (have.status !== 0) {
  log("installing the OpenAI SDK into backend/.venv ...");
  spawnSync(py, ["-m", "pip", "install", "-q", "openai"], { stdio: "inherit" });
}

log("running examples/openai_quickstart.py against the gateway\n");
const run = spawnSync(py, [join(root, "examples", "openai_quickstart.py")], {
  stdio: "inherit",
  env: { ...process.env, LLMFLOW_KEY: key, LLMFLOW_URL: `${API}/v1` },
});

console.log(`\n  Dashboard   ${WEB}   (Requests page shows every call above)`);
console.log(`  Connect     ${WEB}/#/connect   (copy-paste snippets for your own app)\n`);
if (once || run.status !== 0) stop(run.status ?? 1);
else if (started) log("stack is still running; press Ctrl+C to stop");
else process.exit(0);
