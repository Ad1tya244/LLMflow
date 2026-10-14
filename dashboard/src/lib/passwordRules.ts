/** Client-side mirror of the gateway's password policy, for live feedback only.
 *  The server remains the authority and re-checks every password it accepts. */
export interface Rule {
  label: string;
  ok: boolean;
}

const WEAK = ["password", "passw0rd", "qwerty", "asdfgh", "zxcvbn", "letmein", "welcome", "iloveyou", "admin", "changeme", "llmflow"];
const ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890"];

function hasSequence(s: string): boolean {
  for (let i = 0; i + 4 <= s.length; i++) {
    const chunk = s.slice(i, i + 4);
    if (ROWS.some((r) => r.includes(chunk) || [...r].reverse().join("").includes(chunk))) return true;
    const codes = [...chunk].map((c) => c.charCodeAt(0));
    const step = codes[1]! - codes[0]!;
    if (Math.abs(step) === 1 && codes.every((c, k) => k === 0 || c - codes[k - 1]! === step) && /^[a-z0-9]+$/.test(chunk)) return true;
  }
  return false;
}

export function passwordRules(password: string, email = ""): Rule[] {
  const lower = password.toLowerCase();
  const local = email.split("@")[0]?.toLowerCase() ?? "";
  return [
    { label: "At least 12 characters", ok: password.length >= 12 },
    { label: "An uppercase and a lowercase letter", ok: /[A-Z]/.test(password) && /[a-z]/.test(password) },
    { label: "A number", ok: /\d/.test(password) },
    { label: "A symbol or space (! @ # $ %…)", ok: /[^A-Za-z0-9]/.test(password) },
    {
      label: "No repeated or sequential characters (aaaa, 1234, qwer)",
      ok: password.length > 0 && !/(.)\1{3}/i.test(password) && !hasSequence(lower),
    },
    {
      label: "No common words or your email name",
      ok: password.length > 0 && !WEAK.some((w) => lower.includes(w)) && !(local.length >= 4 && lower.includes(local)),
    },
  ];
}

export const passwordAcceptable = (password: string, email = ""): boolean =>
  passwordRules(password, email).every((r) => r.ok);
