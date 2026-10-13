#!/usr/bin/env node
// Operator tooling (not a web portal). Uses the admin key from backend/.env.
//   npm run ops -- workspaces
//   npm run ops -- disable <workspace-id>
//   npm run ops -- enable <workspace-id>
//   npm run ops -- delete <workspace-id>
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const envFile = join(root, "backend", ".env");
const env = {};
if (existsSync(envFile)) {
  for (const l of readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const m = l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^['"]|['"]$/g, "");
  }
}
const base = process.env.LLMFLOW_API_URL ?? `http://localhost:${process.env.LLMFLOW_PORT ?? "8000"}`;
const key = process.env.LLMFLOW_ADMIN_KEY ?? (env.LLMFLOW_ADMIN_API_KEYS ?? "").split(",")[0]?.trim();
if (!key) {
  console.error("No admin key: set LLMFLOW_ADMIN_API_KEYS in backend/.env (or LLMFLOW_ADMIN_KEY).");
  process.exit(1);
}

async function call(method, path) {
  const res = await fetch(`${base}${path}`, { method, headers: { Authorization: `Bearer ${key}` } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    console.error(`error ${res.status}: ${body?.error?.message ?? res.statusText}`);
    process.exit(1);
  }
  return body;
}

const [cmd, id] = process.argv.slice(2);
if (cmd === "workspaces") {
  const { tenants } = await call("GET", "/admin/tenants");
  if (!tenants.length) console.log("no workspaces");
  for (const t of tenants) {
    console.log(
      `${t.id}  ${t.disabled ? "DISABLED" : "active  "}  ${t.owner_email || "-"}  "${t.name}"  ` +
        `providers=[${t.providers.join(",")}]  tokens_today=${t.tokens_today}`,
    );
  }
} else if (["disable", "enable", "delete"].includes(cmd) && id) {
  const out = await call(cmd === "delete" ? "DELETE" : "POST", cmd === "delete" ? `/admin/tenants/${id}` : `/admin/tenants/${id}/${cmd}`);
  console.log(out.status);
} else {
  console.error("usage: npm run ops -- workspaces | disable <id> | enable <id> | delete <id>");
  process.exit(2);
}
