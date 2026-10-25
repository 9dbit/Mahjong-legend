export type Json =
  | null
  | boolean
  | number
  | string
  | Json[]
  | { [key: string]: Json };
export type MathConfig = {
  version: string;
  grid: number[];
  symbols: Record<string, number>;
  paytable: Record<string, number[]>;
  scatter_probability_per_reel: number;
  enhanced_probability_reels_2_to_4: number;
  bonus_all_enhanced_reel: number;
  base_multipliers: number[];
  bonus_multipliers: number[];
  free_spins_for_3_scatters: number;
  extra_free_spins_per_additional_scatter: number;
  paytable_scale_base: string;
  paytable_scale_bonus: string;
  max_round_payout_x: string;
  [key: string]: Json;
};
export type Binding = {
  asset: string | null;
  gain: number;
  bus: string;
  enabled: boolean;
  priority?: number;
  cooldown_ms?: number;
  max_voices?: number;
};
export type Track = {
  asset: string | null;
  gain: number;
  loop_start: number;
  loop_end: number | null;
};
export type StudioConfig = {
  schema_version: number;
  math: MathConfig;
  bet: {
    options: string[];
    default: string;
    initial_balance: string;
    auto_counts: number[];
    auto_stop_on_bonus: boolean;
    auto_stop_on_win_x: number | null;
  };
  presentation: {
    big_win_x: number;
    mega_win_x: number;
    animation_speed: number;
  };
  tiles: Record<string, { normal: string; gold: string }>;
  scene: Record<string, string | null>;
  audio: {
    output_gain: number;
    buses: Record<string, number>;
    events: Record<string, Binding>;
    music: { base: Track | null; bonus: Track | null };
  };
};
export type Validation = {
  valid: boolean;
  errors: (string | { field?: string; message?: string })[];
  warnings: string[];
  receipt?: { hash: string; [key: string]: unknown };
};
export type Draft = {
  id: string;
  name: string;
  revision: number;
  config: StudioConfig;
  status: string;
  validation?: Validation | null;
  updated_at?: string;
  created_at?: string;
};
export type Asset = {
  id: string;
  name: string;
  kind: string;
  status: string;
  is_derivative?: boolean;
  is_baseline?: boolean;
  sha256?: string;
  url: string;
  preview_url?: string;
  metadata: {
    duration?: number;
    duration_seconds?: number;
    sample_rate?: number;
    channels?: number;
    width?: number;
    height?: number;
    peaks?: number[] | number[][];
    waveform?: number[];
    peak_dbfs?: number;
    rms_dbfs?: number;
    peak_db?: number;
    rms_db?: number;
    true_peak_db?: number | null;
    lufs?: number | null;
    true_peak_dbfs?: number | null;
    [key: string]: unknown;
  };
  recipe?: Record<string, unknown>;
  original_id?: string | null;
};
export type Job = {
  id: string;
  kind: string;
  status: string;
  source_asset_id?: string | null;
  progress?: number;
  result?: Record<string, unknown>;
  error?: string;
  created_at?: string;
  updated_at?: string;
  draft_id?: string;
};
export type Release = {
  engine_sha256?: string;
  id: string;
  name?: string;
  version?: string;
  hash?: string;
  sha256?: string;
  created_at?: string;
  activated_at?: string;
  active?: boolean;
  reason?: string;
  config?: StudioConfig;
  [key: string]: unknown;
};
export type Session = {
  authenticated: boolean;
  setup_required?: boolean;
  user?: { username: string; permissions: string[] };
  csrf_token?: string;
  environment?: string;
};
