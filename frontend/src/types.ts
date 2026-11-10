export type Format = 'mp4' | 'mp3' | 'photos' | 'slideshow' | 'photo' | 'png';
export type Status = 'queued' | 'fetching_info' | 'downloading' | 'processing' | 'finishing' | 'cancelling' | 'cancelled' | 'interrupted' | 'completed' | 'error';
export interface Quality { id: string; badge: string; label: string }
export interface MediaInfo {
  url: string; id: string; title: string; uploader: string; thumbnail?: string | null;
  duration: string; duration_seconds: number; platform: { name: string; id: string };
  media_type?: 'video' | 'photos'; photo_count?: number; photos?: { url: string }[];
  has_music?: boolean; music?: { title?: string } | null; qualities: Quality[]; audio_qualities: Quality[];
}
export interface DownloadPayload { url: string; format: Format; quality: string; title: string; photo_index?: number }
export interface Task extends DownloadPayload {
  id: string; status: Status; progress: number; downloaded_bytes: number; total_bytes: number;
  speed: string; eta: string; detail?: string; filename?: string; error?: string | null;
  created_at: number; updated_at: number; completed_at?: number; managed_here?: boolean;
}
export interface MediaFile { filename: string; size: string; size_bytes: number; created_at: number; format: string; kind: 'video' | 'audio' | 'photos' }
export interface UserProfile {
  id?: string;
  email?: string;
  role?: 'owner' | 'admin' | 'member' | 'viewer';
  tenant_id?: string;
  tenant_name?: string;
}
export interface Session {
  mode: 'local' | 'cloud';
  authenticated: boolean;
  user?: UserProfile;
}
export interface TenantUser {
  id: string;
  tenant_id: string;
  email: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  is_active: boolean;
  totp_enabled: boolean;
  created_at: number;
}
export interface AuditLogEntry {
  id: string;
  tenant_id: string;
  user_id?: string;
  actor_email?: string;
  action: string;
  target_type?: string;
  target_id?: string;
  client_ip: string;
  status: string;
  details: Record<string, unknown>;
  created_at: number;
  prev_hash: string;
}
export interface TenantQuotaUsage {
  tier: 'unlimited' | 'pro' | 'free';
  is_unlimited: boolean;
  active_jobs: number;
  max_concurrent_jobs: number;
  daily_jobs_used: number;
  max_daily_jobs: number;
  daily_bytes_used: number;
  max_daily_bytes: number;
  storage_quota_bytes: number;
}
export interface AbuseControls {
  id: number;
  kill_switch_active: boolean;
  blocked_domains: string[];
  allowed_domains: string[];
  updated_at: number;
}

export interface DependencyHealth {
  status: 'ok' | 'degraded' | 'error' | 'warning';
  latency_ms?: number;
  type?: string;
  error?: string;
  fallback?: string;
}

export interface SystemHealthReport {
  status: 'ready' | 'degraded' | 'unhealthy';
  mode: string;
  dependencies: {
    database: DependencyHealth;
    redis?: DependencyHealth;
    storage: DependencyHealth;
  };
  timestamp: number;
}
export const terminal = new Set<Status>(['completed', 'error', 'cancelled', 'interrupted']);
