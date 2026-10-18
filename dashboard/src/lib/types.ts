export type Tier = "small" | "medium" | "large";
export type RangeKey = "1h" | "24h" | "7d" | "30d";

export interface SeriesPoint {
  ts: number;
  requests: number;
  errors: number;
  tokens: number;
  shadow_cost_usd: number;
  reference_cost_usd: number;
  small: number;
  medium: number;
  large: number;
}

export interface ModelRollup {
  model: string;
  provider: string | null;
  tier: Tier | null;
  requests: number;
  tokens: number;
  shadow_cost_usd: number;
  p50_latency_ms: number | null;
}

export interface Overview {
  range_start: number;
  bucket_s: number;
  totals: {
    requests: number;
    errors: number;
    error_rate: number;
    tokens: number;
    shadow_cost_usd: number;
    p50_latency_ms: number | null;
    p95_latency_ms: number | null;
    cache_hits: number;
    cache_lookups: number;
    cache_hit_rate: number | null;
    reference_model: string | null;
    reference_cost_usd: number | null;
    saved_vs_reference_usd: number | null;
  };
  series: SeriesPoint[];
  by_model: ModelRollup[];
}

export interface RequestRow {
  id: number;
  ts: number;
  requested_model: string;
  model: string | null;
  provider: string | null;
  status: "ok" | "error";
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  shadow_cost_usd: number;
  attempts: number;
  route_reason: string;
  cache_status: "none" | "miss" | "hit";
}

export interface RequestPage {
  total: number;
  items: RequestRow[];
}

export interface ApiKeyInfo {
  id: string;
  name: string;
  last4: string;
  created_at: number;
  last_used_at: number | null;
  revoked_at: number | null;
  /** True when the full key can be shown again after re-entering the password. */
  revealable?: boolean;
}

export interface AuditEvent {
  ts: number;
  actor: string;
  action: string;
  detail: string;
  ip: string;
}

export interface PublicInfo {
  password_min_length?: number;
  byok_enabled: boolean;
  signup_enabled: boolean;
  invite_code_required: boolean;
}

export interface AccountProvider {
  id: string;
  configured: boolean;
  last4: string | null;
  trains_on_data: boolean;
  auth_failed: boolean;
}

export interface AccountInfo {
  workspace: { id: string; name: string; created_at: number };
  user: { email: string; last_login_at: number | null; mfa_enabled: boolean };
  recovery_codes_left: number;
  providers: AccountProvider[];
  models: { id: string; provider: string; upstream_model: string; tier: Tier; enabled: boolean }[];
  usage_today: { tokens: number; shadow_cost_usd: number };
  limits: { daily_budget_usd: number | null; daily_token_budget: number | null; rate_limit_rpm: number };
}


export interface WorkspaceSettings {
  cache_mode: "auto" | "always" | "off";
  default_quality: "low" | "balanced" | "high";
  daily_budget_usd: number | null;
  daily_token_budget: number | null;
  platform_caps: { daily_budget_usd: number | null; daily_token_budget: number | null };
}

export interface SessionRow {
  id: string;
  created_at: number;
  last_seen_at: number;
  ip: string;
  user_agent: string;
  current: boolean;
}
