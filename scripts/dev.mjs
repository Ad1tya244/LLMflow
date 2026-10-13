#!/usr/bin/env node
// One-command dev runner: prepares dependencies and config on first run, then starts
// the API (uvicorn, auto-reload) and the dashboard (Vite) together. Zero npm dependencies.
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, statSync, watch, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const dashboard = join(root, "dashboard");
const win = process.platform === "win32";
const venvBin = join(backend, ".venv", win ? "Scripts" : "bin");
const venvPython = join(venvBin, win ? "python.exe" : "python");
const API_PORT = process.env.LLMFLOW_PORT ?? "8000";
const WEB_PORT = process.env.LLMFLOW_WEB_PORT ?? "5173";

const c = (code, s) => (process.stdout.isTTY ? `\x1b[${code}m${s}\x1b[0m` : s);
const say = (s) => console.log(`${c(2, "[dev]")} ${s}`);
const die = (s) => {
  console.error(`${c(31, "[dev]")} ${s}`);
  process.exit(1);
};

function run(cmd, args, cwd, label) {
  say(label);
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit", shell: win });
  if (r.status !== 0) die(`failed: ${cmd} ${args.join(" ")}`);
}

const newer = (a, b) => !existsSync(b) || statSync(a).mtimeMs > statSync(b).mtimeMs;

function ensureBackend() {
  if (!existsSync(venvPython)) {
    const py = spawnSync(win ? "python" : "python3", ["--version"], { encoding: "utf8" });
    if (py.status !== 0) die("Python 3.12+ is required but was not found on PATH.");
    run(win ? "python" : "python3", ["-m", "venv", ".venv"], backend, "creating Python virtualenv (first run)");
  }
  const marker = join(backend, ".venv", ".llmflow-deps");
  if (newer(join(backend, "pyproject.toml"), marker)) {
    run(venvPython, ["-m", "pip", "install", "-q", "-e", ".[dev]"], backend, "installing backend dependencies");
    writeFileSync(marker, new Date().toISOString());
  }
}

function ensureDashboard() {
  const lock = join(dashboard, "node_modules", ".package-lock.json");
  if (newer(join(dashboard, "package.json"), lock)) {
    run(win ? "npm.cmd" : "npm", ["install", "--no-audit", "--no-fund"], dashboard, "installing dashboard dependencies");
  }
}

function parseEnv(text) {
  const env = {};
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^['"]|['"]$/g, "");
  }
  return env;
}

function ensureEnv() {
  const envFile = join(backend, ".env");
  if (!existsSync(envFile)) {
    const key = `llmflow-dev-${randomBytes(12).toString("hex")}`;
    const text = readFileSync(join(backend, ".env.example"), "utf8").replace(
      /^LLMFLOW_API_KEYS=.*$/m,
      `LLMFLOW_API_KEYS=${key}`,
    );
    writeFileSync(envFile, text);
    say("created backend/.env with a generated local API key");
  }
  // Keys added after the first version of this file existed are filled in on later runs.
  let env = parseEnv(readFileSync(envFile, "utf8"));
  const additions = [];
  if (!env.LLMFLOW_ADMIN_API_KEYS) {
    additions.push(`LLMFLOW_ADMIN_API_KEYS=llmflow-admin-${randomBytes(12).toString("hex")}`);
  }
  if (!("LLMFLOW_ENABLE_DOCS" in env)) additions.push("LLMFLOW_ENABLE_DOCS=true");
  // Master key for encrypting workspace (bring-your-own) provider keys. Losing it makes the
  // stored keys unrecoverable, so it is generated once and never rotated automatically.
  if (!env.LLMFLOW_MASTER_KEY) {
    additions.push(
      `LLMFLOW_MASTER_KEY=${randomBytes(32).toString("base64").replace(/\+/g, "-").replace(/\//g, "_")}`,
    );
  }
  if (!("LLMFLOW_SIGNUP_ENABLED" in env)) additions.push("LLMFLOW_SIGNUP_ENABLED=true");
  if (additions.length) {
    const current = readFileSync(envFile, "utf8");
    writeFileSync(envFile, `${current.replace(/\s*$/, "\n")}${additions.join("\n")}\n`);
    say("updated backend/.env (admin key, master key, sign-up flag)");
    env = parseEnv(readFileSync(envFile, "utf8"));
  }
  return env;
}

function prefix(label, color, stream) {
  let buf = "";
  stream.on("data", (chunk) => {
    buf += chunk.toString();
    const lines = buf.split(/\r?\n/);
    buf = lines.pop() ?? "";
    for (const l of lines) console.log(`${c(color, label)} ${l}`);
  });
}

ensureBackend();
ensureDashboard();
const dotenv = ensureEnv();

const children = new Set();
let stopping = false;
const restarting = new Set();

function start(label, color, cmd, args, cwd, env) {
  const child = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, shell: win });
  prefix(label, color, child.stdout);
  prefix(label, color, child.stderr);
  child.on("exit", (code, signal) => {
    children.delete(child);
    if (stopping || restarting.has(child)) return;
    console.error(`${c(31, "[dev]")} ${label.trim()} exited (${signal ?? code}); shutting down`);
    shutdown(code || 1);
  });
  children.add(child);
  return child;
}

function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const ch of children) ch.kill("SIGTERM");
  setTimeout(() => process.exit(code), 500).unref();
}
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

const startApi = () =>
  start(
    "[api]", 36,
    join(venvBin, win ? "uvicorn.exe" : "uvicorn"),
    [
      "--factory", "llmflow.api.app:create_app",
      "--host", "127.0.0.1", "--port", API_PORT, "--no-server-header",
      "--reload", "--reload-dir", "src", "--reload-dir", "config",
    ],
    backend,
    { PYTHONPATH: join(backend, "src") },
  );
let api = startApi();

// uvicorn only watches source dirs; restart the API ourselves when backend/.env changes.
let debounce;
watch(join(backend, ".env"), () => {
  clearTimeout(debounce);
  debounce = setTimeout(() => {
    say("backend/.env changed; restarting API");
    restarting.add(api);
    api.once("exit", () => {
      restarting.delete(api);
      api = startApi();
    });
    api.kill("SIGTERM");
  }, 300);
});

start(
  "[web]", 35,
  win ? "npx.cmd" : "npx",
  ["vite", "--port", WEB_PORT, "--strictPort"],
  dashboard,
  { VITE_GATEWAY_URL: `http://localhost:${API_PORT}` },
);

const providerKeys = ["GROQ_API_KEY"];
const configured = providerKeys.filter((k) => (dotenv[k] ?? process.env[k] ?? "").trim());
setTimeout(() => {
  console.log("");
  console.log(`  ${c(1, "LLMFlow is running")}`);
  console.log(`  Dashboard   http://localhost:${WEB_PORT}   (create a workspace to get started)`);
  console.log(`  API         http://localhost:${API_PORT}   (OpenAI-compatible: /v1/chat/completions)`);
  console.log(`  API docs    http://localhost:${API_PORT}/docs`);
  console.log(
    configured.length
      ? `  Providers   ${configured.map((k) => k.replace("_API_KEY", "")).join(", ")}`
      : `  Providers   none yet - add GROQ_API_KEY (console.groq.com) to backend/.env; the API restarts automatically`,
  );
  console.log("");
}, 2500);
