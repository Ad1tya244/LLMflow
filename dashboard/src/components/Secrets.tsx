import { Check, Copy, Download } from "lucide-react";
import { useState } from "react";

/** A secret shown exactly once, with copy (and optional download) affordances. */
export function SecretBlock({
  title,
  value,
  filename,
}: {
  title: string;
  value: string;
  filename?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable: the text is still selectable */
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([value], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = filename ?? "llmflow-secret.txt";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="form-row" style={{ justifyContent: "space-between" }}>
        <b>{title}</b>
        <div className="form-row" style={{ gap: 8 }}>
          <button className="btn" onClick={() => void copy()}>
            {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
            {copied ? "Copied" : "Copy"}
          </button>
          {filename && (
            <button className="btn" onClick={download}>
              <Download size={14} aria-hidden />
              Download
            </button>
          )}
        </div>
      </div>
      <pre className="codeblock" style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
        {value}
      </pre>
    </div>
  );
}
