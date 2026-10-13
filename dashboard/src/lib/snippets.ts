export interface Snippet {
  id: string;
  title: string;
  language: string;
  code: string;
}

const KEY = "<YOUR_LLMFLOW_API_KEY>";

/** Copy-paste integration snippets for a gateway at ``baseUrl`` (no trailing path). */
export function buildSnippets(baseUrl: string): Snippet[] {
  const v1 = `${baseUrl.replace(/\/+$/, "")}/v1`;
  return [
    {
      id: "env",
      title: "No code changes (environment variables)",
      language: "bash",
      code: `# Any app that uses the OpenAI SDK picks these up automatically.
export OPENAI_BASE_URL=${v1}
export OPENAI_API_KEY=${KEY}
# then use model="auto" (or any model id from the list above) in your app`,
    },
    {
      id: "python",
      title: "Python (openai SDK)",
      language: "python",
      code: `from openai import OpenAI

client = OpenAI(base_url="${v1}", api_key="${KEY}")

reply = client.chat.completions.create(
    model="auto",  # LLMFlow picks the cheapest model that should answer well
    messages=[{"role": "user", "content": "Hello!"}],
    extra_body={"llmflow": {"quality": "balanced"}},  # optional: low | balanced | high
)
print(reply.choices[0].message.content)`,
    },
    {
      id: "node",
      title: "Node.js (openai SDK)",
      language: "javascript",
      code: `import OpenAI from "openai";

const client = new OpenAI({ baseURL: "${v1}", apiKey: "${KEY}" });

const reply = await client.chat.completions.create({
  model: "auto",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(reply.choices[0].message.content);`,
    },
    {
      id: "curl",
      title: "curl",
      language: "bash",
      code: `curl ${v1}/chat/completions \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'`,
    },
  ];
}
