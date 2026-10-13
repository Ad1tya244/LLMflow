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

export interface StrategyResult {
  description: string;
  n: number;
  passed: number;
  accuracy: number;
  accuracy_ci95: [number, number];
  failures: number;
  fallbacks: number;
  retries: number;
  latency_ms_mean: number | null;
  latency_ms_p50: number | null;
  latency_ms_p95: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  shadow_cost_usd: number;
  cost_per_correct_usd: number | null;
  tier_mix: Record<string, number>;
  models_used: Record<string, number>;
  by_difficulty: Record<string, { n: number; accuracy: number }>;
  by_category: Record<string, { n: number; accuracy: number }>;
  accuracy_delta_vs_large_pts?: number;
  cost_saving_vs_large_pct?: number | null;
  latency_p50_delta_vs_large_pct?: number | null;
}

export interface BenchmarkReport {
  label: "MEASURED";
  notes?: string[];
  generated_at: string;
  suite: string;
  items: number;
  models: Record<string, { upstream: string; tier: string; price_in: number; price_out: number }>;
  strategies: Record<string, StrategyResult>;
  suggested_quality_priors: Record<string, { n: number; accuracy: number; current_prior: number | null }>;
}

export interface BenchmarksResponse {
  available: string[];
  selected: string | null;
  report: BenchmarkReport | null;
}

export interface ApiKeyInfo {
  id: string;
  name: string;
  last4: string;
  created_at: number;
  last_used_at: number | null;
  revoked_at: number | null;
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

