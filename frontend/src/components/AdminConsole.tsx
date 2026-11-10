import { useEffect, useState } from 'react';
import { Activity, Ban, CheckCircle2, Download, Flame, KeyRound, Server, ShieldAlert, ShieldCheck, UserCheck, UserPlus, Users, Zap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { api } from '@/lib/api';
import type { AbuseControls, AuditLogEntry, SystemHealthReport, TenantQuotaUsage, TenantUser, UserProfile } from '@/types';

interface AdminConsoleProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentUser?: UserProfile;
}

export function AdminConsole({ open, onOpenChange, currentUser }: AdminConsoleProps) {
  const [tab, setTab] = useState<'users' | 'audit' | 'mfa' | 'quotas' | 'health'>('users');
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [quota, setQuota] = useState<TenantQuotaUsage | null>(null);
  const [abuse, setAbuse] = useState<AbuseControls | null>(null);
  const [healthReport, setHealthReport] = useState<SystemHealthReport | null>(null);
  const [blockedDomainInput, setBlockedDomainInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verifyStatus, setVerifyStatus] = useState<string | null>(null);

  // New User form
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<'owner' | 'admin' | 'member' | 'viewer'>('member');

  // MFA form
  const [mfaSecret, setMfaSecret] = useState<string | null>(null);
  const [mfaUri, setMfaUri] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState('');
  const [mfaMessage, setMfaMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (tab === 'users') {
      setLoading(true);
      api<{ users: TenantUser[] }>('/api/admin/users')
        .then(res => setUsers(res.users))
        .catch(err => setError(err.message))
        .finally(() => setLoading(false));
    } else if (tab === 'audit') {
      setLoading(true);
      api<{ logs: AuditLogEntry[] }>('/api/admin/audit-logs')
        .then(res => setAuditLogs(res.logs))
        .catch(err => setError(err.message))
        .finally(() => setLoading(false));
    } else if (tab === 'quotas') {
      setLoading(true);
      Promise.all([
        api<TenantQuotaUsage>('/api/quotas/usage').then(setQuota),
        api<AbuseControls>('/api/admin/abuse-controls').then(setAbuse),
      ])
        .catch(err => setError(err.message))
        .finally(() => setLoading(false));
    } else if (tab === 'health') {
      setLoading(true);
      api<SystemHealthReport>('/api/health/ready')
        .then(setHealthReport)
        .catch(err => setError(err.message))
        .finally(() => setLoading(false));
    }
  }, [open, tab]);

  async function handleRefreshHealth() {
    setLoading(true);
    setError(null);
    try {
      const res = await api<SystemHealthReport>('/api/health/ready');
      setHealthReport(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to query health probes.');
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateUser(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api('/api/admin/users', {
        method: 'POST',
        body: { email: newEmail, password: newPassword, role: newRole },
      });
      setNewEmail('');
      setNewPassword('');
      const refreshed = await api<{ users: TenantUser[] }>('/api/admin/users');
      setUsers(refreshed.users);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not create user.');
    }
  }

  async function handleRoleChange(userId: string, role: string) {
    try {
      await api(`/api/admin/users/${userId}/role`, {
        method: 'PATCH',
        body: { role },
      });
      const refreshed = await api<{ users: TenantUser[] }>('/api/admin/users');
      setUsers(refreshed.users);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not update role.');
    }
  }

  async function handleVerifyAuditChain() {
    try {
      setVerifyStatus('Verifying cryptographic hash chain…');
      const res = await api<{ verified: boolean }>('/api/admin/audit-logs/verify');
      if (res.verified) {
        setVerifyStatus('Cryptographic verification succeeded. Hash chain is intact and tamper-evident.');
      } else {
        setVerifyStatus('ALERT: Tamper detected! Hash chain verification failed.');
      }
    } catch (err: unknown) {
      setVerifyStatus(err instanceof Error ? err.message : 'Verification failed.');
    }
  }

  async function handleMfaSetup() {
    try {
      setMfaMessage(null);
      const res = await api<{ secret: string; provisioning_uri: string }>('/api/auth/mfa/setup', {
        method: 'POST',
      });
      setMfaSecret(res.secret);
      setMfaUri(res.provisioning_uri);
    } catch (err: unknown) {
      setMfaMessage(err instanceof Error ? err.message : 'MFA setup failed.');
    }
  }

  async function handleMfaEnable(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api('/api/auth/mfa/enable', {
        method: 'POST',
        body: { code: mfaCode },
      });
      setMfaMessage('Two-Factor Authentication is now enabled on your account!');
      setMfaSecret(null);
      setMfaCode('');
    } catch (err: unknown) {
      setMfaMessage(err instanceof Error ? err.message : 'Invalid verification code.');
    }
  }

  async function handleToggleKillSwitch() {
    if (!abuse) return;
    try {
      const res = await api<AbuseControls>('/api/admin/kill-switch', {
        method: 'POST',
        body: { active: !abuse.kill_switch_active },
      });
      setAbuse(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to toggle kill switch.');
    }
  }

  async function handleUpdateTier(newTier: 'unlimited' | 'pro' | 'free') {
    const tenantId = currentUser?.tenant_id || 'default-tenant';
    try {
      await api(`/api/admin/tenants/${tenantId}/tier`, {
        method: 'POST',
        body: { tier: newTier },
      });
      const updated = await api<TenantQuotaUsage>('/api/quotas/usage');
      setQuota(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to update tenant tier.');
    }
  }

  async function handleAddBlockedDomain(e: React.FormEvent) {
    e.preventDefault();
    if (!blockedDomainInput.trim() || !abuse) return;
    const nextDomains = Array.from(new Set([...abuse.blocked_domains, blockedDomainInput.trim().toLowerCase()]));
    try {
      const res = await api<AbuseControls>('/api/admin/abuse-controls', {
        method: 'PUT',
        body: { blocked_domains: nextDomains },
      });
      setAbuse(res);
      setBlockedDomainInput('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to update domain blocklist.');
    }
  }

  async function handleRemoveBlockedDomain(domain: string) {
    if (!abuse) return;
    const nextDomains = abuse.blocked_domains.filter(d => d !== domain);
    try {
      const res = await api<AbuseControls>('/api/admin/abuse-controls', {
        method: 'PUT',
        body: { blocked_domains: nextDomains },
      });
      setAbuse(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to remove domain.');
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="text-emerald-400" size={20} />
            <span>Workspace Administration</span>
          </DialogTitle>
          <DialogDescription>
            Manage users, role permissions, two-factor authentication, and tamper-evident audit logs.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="p-3 bg-red-950/50 border border-red-800 text-red-200 rounded text-sm flex items-center gap-2">
            <ShieldAlert size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* Tab Navigation */}
        <div className="flex gap-2 border-b border-border pb-2">
          <Button
            variant={tab === 'users' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTab('users')}
            className="gap-2"
          >
            <Users size={15} />
            <span>Users & RBAC</span>
          </Button>
          <Button
            variant={tab === 'audit' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTab('audit')}
            className="gap-2"
          >
            <ShieldCheck size={15} />
            <span>Audit Trail</span>
          </Button>
          <Button
            variant={tab === 'mfa' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTab('mfa')}
            className="gap-2"
          >
            <KeyRound size={15} />
            <span>MFA Security</span>
          </Button>
          <Button
            variant={tab === 'quotas' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTab('quotas')}
            className="gap-2"
          >
            <Activity size={15} />
            <span>Quotas & Abuse</span>
          </Button>
          <Button
            variant={tab === 'health' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTab('health')}
            className="gap-2"
          >
            <Server size={15} />
            <span>Health & SRE</span>
          </Button>
        </div>

        {/* USERS TAB */}
        {tab === 'users' && (
          <div className="space-y-4 pt-2">
            {currentUser?.role === 'owner' || currentUser?.role === 'admin' ? (
              <form onSubmit={handleCreateUser} className="p-4 bg-muted/40 rounded-lg space-y-3">
                <h4 className="text-sm font-semibold flex items-center gap-2">
                  <UserPlus size={15} /> Add Workspace Member
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  <Input
                    placeholder="member@company.com"
                    type="email"
                    value={newEmail}
                    onChange={e => setNewEmail(e.target.value)}
                    required
                  />
                  <Input
                    placeholder="Temporary password"
                    type="password"
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    required
                  />
                  <select
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    value={newRole}
                    onChange={e => setNewRole(e.target.value as any)}
                  >
                    <option value="member">Member (Downloads)</option>
                    <option value="viewer">Viewer (Read-only)</option>
                    <option value="admin">Admin (Manage)</option>
                    {currentUser?.role === 'owner' && <option value="owner">Owner</option>}
                  </select>
                </div>
                <Button type="submit" size="sm" className="w-full sm:w-auto">
                  Provision User
                </Button>
              </form>
            ) : null}

            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs uppercase bg-muted/50 text-muted-foreground border-b border-border">
                  <tr>
                    <th className="px-3 py-2">Email</th>
                    <th className="px-3 py-2">Role</th>
                    <th className="px-3 py-2">MFA</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {users.map(u => (
                    <tr key={u.id} className="hover:bg-muted/20">
                      <td className="px-3 py-2 font-medium">{u.email}</td>
                      <td className="px-3 py-2">
                        <span className="inline-block px-2 py-0.5 text-xs rounded bg-primary/20 text-primary-foreground font-mono">
                          {u.role}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        {u.totp_enabled ? (
                          <span className="text-emerald-400 text-xs flex items-center gap-1">
                            <CheckCircle2 size={12} /> Active
                          </span>
                        ) : (
                          <span className="text-muted-foreground text-xs">Off</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs">{u.is_active ? 'Active' : 'Deactivated'}</td>
                      <td className="px-3 py-2">
                        {currentUser?.role === 'owner' && u.id !== currentUser.id && (
                          <select
                            className="text-xs rounded border border-border bg-background px-1 py-0.5"
                            value={u.role}
                            onChange={e => handleRoleChange(u.id, e.target.value)}
                          >
                            <option value="viewer">Viewer</option>
                            <option value="member">Member</option>
                            <option value="admin">Admin</option>
                            <option value="owner">Owner</option>
                          </select>
                        )}
                      </td>
                    </tr>
                  ))}
                  {users.length === 0 && !loading && (
                    <tr>
                      <td colSpan={5} className="text-center py-4 text-muted-foreground">
                        No members found in this tenant.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* AUDIT LOG TAB */}
        {tab === 'audit' && (
          <div className="space-y-4 pt-2">
            <div className="flex flex-wrap items-center justify-between gap-2 p-3 bg-muted/40 rounded-lg">
              <div>
                <h4 className="text-sm font-semibold">Cryptographic Audit Chain</h4>
                <p className="text-xs text-muted-foreground">
                  Every security and media event is hashed and chained with SHA-256 to ensure tamper evidence.
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={handleVerifyAuditChain} className="gap-1">
                  <ShieldCheck size={14} /> Verify Integrity
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => window.open('/api/admin/audit-logs/export', '_blank')}
                  className="gap-1"
                >
                  <Download size={14} /> Export CSV
                </Button>
              </div>
            </div>

            {verifyStatus && (
              <div
                className={`p-2.5 rounded text-xs font-mono border ${
                  verifyStatus.includes('succeeded')
                    ? 'bg-emerald-950/40 border-emerald-800 text-emerald-300'
                    : 'bg-amber-950/40 border-amber-800 text-amber-300'
                }`}
              >
                {verifyStatus}
              </div>
            )}

            <div className="overflow-x-auto max-h-72">
              <table className="w-full text-xs text-left">
                <thead className="uppercase bg-muted/50 text-muted-foreground sticky top-0 border-b border-border">
                  <tr>
                    <th className="px-2 py-1.5">Action</th>
                    <th className="px-2 py-1.5">Actor</th>
                    <th className="px-2 py-1.5">IP</th>
                    <th className="px-2 py-1.5">Target</th>
                    <th className="px-2 py-1.5">Status</th>
                    <th className="px-2 py-1.5">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {auditLogs.map(l => (
                    <tr key={l.id} className="hover:bg-muted/20 font-mono">
                      <td className="px-2 py-1.5 font-semibold text-primary">{l.action}</td>
                      <td className="px-2 py-1.5">{l.actor_email || 'anonymous'}</td>
                      <td className="px-2 py-1.5">{l.client_ip}</td>
                      <td className="px-2 py-1.5">{l.target_id || '-'}</td>
                      <td className="px-2 py-1.5">
                        <span
                          className={
                            l.status === 'success'
                              ? 'text-emerald-400'
                              : l.status === 'denied'
                              ? 'text-amber-400'
                              : 'text-red-400'
                          }
                        >
                          {l.status}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-muted-foreground">
                        {new Date(l.created_at * 1000).toLocaleTimeString()}
                      </td>
                    </tr>
                  ))}
                  {auditLogs.length === 0 && !loading && (
                    <tr>
                      <td colSpan={6} className="text-center py-4 text-muted-foreground">
                        No audit records recorded yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* MFA TAB */}
        {tab === 'mfa' && (
          <div className="space-y-4 pt-2">
            <div className="p-4 bg-muted/40 rounded-lg space-y-3">
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <KeyRound size={16} /> Two-Factor Authentication (TOTP)
              </h4>
              <p className="text-xs text-muted-foreground">
                Enhance your account security with an authenticator app (Google Authenticator, 1Password, Authy).
              </p>

              {!mfaSecret ? (
                <Button size="sm" onClick={handleMfaSetup}>
                  Configure Authenticator App
                </Button>
              ) : (
                <form onSubmit={handleMfaEnable} className="space-y-3 border-t border-border pt-3">
                  <div className="text-xs font-mono break-all p-2 bg-background border border-border rounded">
                    Secret key: <strong>{mfaSecret}</strong>
                    <br />
                    URI: <span className="text-muted-foreground">{mfaUri}</span>
                  </div>
                  <div className="flex gap-2">
                    <Input
                      placeholder="6-digit code"
                      maxLength={6}
                      value={mfaCode}
                      onChange={e => setMfaCode(e.target.value)}
                      required
                    />
                    <Button type="submit" size="sm">
                      Verify & Activate
                    </Button>
                  </div>
                </form>
              )}

              {mfaMessage && (
                <p className="text-xs text-emerald-400 font-medium">{mfaMessage}</p>
              )}
            </div>
          </div>
        )}

        {/* QUOTAS & ABUSE TAB */}
        {tab === 'quotas' && (
          <div className="space-y-4 pt-2">
            {/* Current Workspace Tier Card */}
            <div className="p-4 bg-muted/40 rounded-lg space-y-3 border border-border">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-semibold flex items-center gap-2">
                    <Zap className={quota?.is_unlimited ? "text-amber-400" : "text-blue-400"} size={16} />
                    <span>Workspace Plan Tier</span>
                  </h4>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Defines rate limits, concurrency clamps, and daily media quotas.
                  </p>
                </div>
                {quota?.is_unlimited ? (
                  <span className="px-3 py-1 bg-amber-500/20 border border-amber-500/40 text-amber-300 rounded-full text-xs font-semibold flex items-center gap-1.5 shadow-sm">
                    👑 Unlimited Plan (Owner - No Limits)
                  </span>
                ) : (
                  <span className="px-3 py-1 bg-secondary text-secondary-foreground rounded-full text-xs font-semibold uppercase">
                    {quota?.tier || 'Free'} Plan
                  </span>
                )}
              </div>

              {/* Usage Cards */}
              <div className="grid grid-cols-3 gap-3 pt-2">
                <div className="p-3 bg-background border border-border rounded-md">
                  <div className="text-xs text-muted-foreground font-medium">Active Downloads</div>
                  <div className="text-lg font-bold mt-1">
                    {quota?.is_unlimited ? (
                      <span className="text-emerald-400">Unlimited</span>
                    ) : (
                      `${quota?.active_jobs || 0} / ${quota?.max_concurrent_jobs}`
                    )}
                  </div>
                </div>
                <div className="p-3 bg-background border border-border rounded-md">
                  <div className="text-xs text-muted-foreground font-medium">Daily Jobs Used</div>
                  <div className="text-lg font-bold mt-1">
                    {quota?.is_unlimited ? (
                      <span className="text-emerald-400">Unlimited</span>
                    ) : (
                      `${quota?.daily_jobs_used || 0} / ${quota?.max_daily_jobs}`
                    )}
                  </div>
                </div>
                <div className="p-3 bg-background border border-border rounded-md">
                  <div className="text-xs text-muted-foreground font-medium">Daily Bandwidth</div>
                  <div className="text-lg font-bold mt-1">
                    {quota?.is_unlimited ? (
                      <span className="text-emerald-400">Unlimited</span>
                    ) : (
                      `${Math.round((quota?.daily_bytes_used || 0) / (1024 * 1024))} MB`
                    )}
                  </div>
                </div>
              </div>

              {currentUser?.role === 'owner' && (
                <div className="pt-2 border-t border-border flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Change Tenant Tier:</span>
                  <div className="flex gap-2">
                    <Button
                      variant={quota?.tier === 'unlimited' ? 'secondary' : 'outline'}
                      size="sm"
                      onClick={() => handleUpdateTier('unlimited')}
                    >
                      👑 Unlimited
                    </Button>
                    <Button
                      variant={quota?.tier === 'pro' ? 'secondary' : 'outline'}
                      size="sm"
                      onClick={() => handleUpdateTier('pro')}
                    >
                      Pro
                    </Button>
                    <Button
                      variant={quota?.tier === 'free' ? 'secondary' : 'outline'}
                      size="sm"
                      onClick={() => handleUpdateTier('free')}
                    >
                      Free
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {/* Emergency Abuse Kill Switch */}
            <div className={`p-4 rounded-lg border space-y-2 ${abuse?.kill_switch_active ? 'bg-red-950/40 border-red-800' : 'bg-muted/40 border-border'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-semibold flex items-center gap-2">
                    <Flame className={abuse?.kill_switch_active ? "text-red-400 animate-pulse" : "text-muted-foreground"} size={16} />
                    <span>Emergency Kill Switch</span>
                  </h4>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {abuse?.kill_switch_active
                      ? "EMERGENCY ACTIVE: Non-owner downloads are blocked platform-wide."
                      : "Pause all downloads across the system immediately during attacks or maintenance."}
                  </p>
                </div>
                <Button
                  variant={abuse?.kill_switch_active ? "destructive" : "outline"}
                  size="sm"
                  onClick={handleToggleKillSwitch}
                >
                  {abuse?.kill_switch_active ? "Deactivate Kill Switch" : "Activate Kill Switch"}
                </Button>
              </div>
            </div>

            {/* Blocked Domains Manager */}
            <div className="p-4 bg-muted/40 rounded-lg border border-border space-y-3">
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <Ban size={16} className="text-amber-400" />
                <span>Abuse Domain Blocklist</span>
              </h4>
              <p className="text-xs text-muted-foreground">
                Prohibit downloads from specific malicious, infringing, or high-bandwidth domains.
              </p>
              <form onSubmit={handleAddBlockedDomain} className="flex gap-2">
                <Input
                  placeholder="e.g. maliciousexample.com"
                  value={blockedDomainInput}
                  onChange={e => setBlockedDomainInput(e.target.value)}
                  className="text-xs"
                />
                <Button type="submit" size="sm" variant="outline">
                  Block Domain
                </Button>
              </form>

              {abuse?.blocked_domains && abuse.blocked_domains.length > 0 ? (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {abuse.blocked_domains.map(dom => (
                    <span
                      key={dom}
                      className="px-2 py-0.5 bg-background border border-border rounded text-xs flex items-center gap-1.5 font-mono"
                    >
                      <span>{dom}</span>
                      <button
                        type="button"
                        onClick={() => handleRemoveBlockedDomain(dom)}
                        className="text-muted-foreground hover:text-red-400 text-xs font-bold"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground italic">No domains currently blocked.</p>
              )}
            </div>
          </div>
        )}

        {/* HEALTH & SRE TAB */}
        {tab === 'health' && (
          <div className="space-y-4 pt-2">
            <div className="flex items-center justify-between p-4 bg-muted/40 rounded-lg border border-border">
              <div>
                <h4 className="text-sm font-semibold flex items-center gap-2">
                  <Server size={16} className="text-sky-400" />
                  <span>Platform Operational Health</span>
                </h4>
                <p className="text-xs text-muted-foreground">
                  Live dependency status, cluster probes, and self-healing degradation status.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`px-2.5 py-1 text-xs font-semibold uppercase tracking-wider rounded-full border ${
                    healthReport?.status === 'ready'
                      ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800'
                      : healthReport?.status === 'degraded'
                      ? 'bg-amber-950/60 text-amber-400 border-amber-800'
                      : 'bg-red-950/60 text-red-400 border-red-800'
                  }`}
                >
                  {healthReport?.status || 'Unknown'}
                </span>
                <Button size="sm" variant="outline" onClick={handleRefreshHealth} disabled={loading}>
                  Refresh
                </Button>
              </div>
            </div>

            {/* Dependency Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {/* Database Card */}
              <div className="p-3 bg-muted/30 border border-border rounded-lg space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-muted-foreground uppercase">Database</span>
                  <span
                    className={`h-2 w-2 rounded-full ${
                      healthReport?.dependencies.database.status === 'ok' ? 'bg-emerald-400' : 'bg-red-500'
                    }`}
                  />
                </div>
                <div className="text-sm font-bold capitalize">
                  {healthReport?.dependencies.database.type || 'PostgreSQL'}
                </div>
                <div className="text-xs text-muted-foreground flex justify-between">
                  <span>Latency:</span>
                  <span className="font-mono">{healthReport?.dependencies.database.latency_ms ?? '—'} ms</span>
                </div>
              </div>

              {/* Redis Broker Card */}
              <div className="p-3 bg-muted/30 border border-border rounded-lg space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-muted-foreground uppercase">Redis Broker</span>
                  <span
                    className={`h-2 w-2 rounded-full ${
                      healthReport?.dependencies.redis?.status === 'ok'
                        ? 'bg-emerald-400'
                        : healthReport?.dependencies.redis?.status === 'degraded'
                        ? 'bg-amber-400'
                        : 'bg-muted-foreground'
                    }`}
                  />
                </div>
                <div className="text-sm font-bold capitalize">
                  {healthReport?.dependencies.redis?.status === 'degraded' ? 'Degraded (SQL Fallback)' : 'Pub/Sub Broker'}
                </div>
                <div className="text-xs text-muted-foreground flex justify-between">
                  <span>Latency:</span>
                  <span className="font-mono">{healthReport?.dependencies.redis?.latency_ms ?? '—'} ms</span>
                </div>
              </div>

              {/* Storage Card */}
              <div className="p-3 bg-muted/30 border border-border rounded-lg space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-muted-foreground uppercase">Object Storage</span>
                  <span
                    className={`h-2 w-2 rounded-full ${
                      healthReport?.dependencies.storage.status === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'
                    }`}
                  />
                </div>
                <div className="text-sm font-bold capitalize">
                  {healthReport?.dependencies.storage.type === 's3' ? 'S3 / RustFS' : 'Local Disk'}
                </div>
                <div className="text-xs text-muted-foreground flex justify-between">
                  <span>Latency:</span>
                  <span className="font-mono">{healthReport?.dependencies.storage.latency_ms ?? '—'} ms</span>
                </div>
              </div>
            </div>

            {/* SRE Metrics & Prometheus Link */}
            <div className="p-4 bg-muted/20 border border-border rounded-lg flex items-center justify-between">
              <div>
                <h5 className="text-xs font-semibold">Prometheus Metrics Exposition</h5>
                <p className="text-xs text-muted-foreground">
                  Scrape endpoint active at <code className="font-mono text-emerald-400">/metrics</code> for Grafana dashboards.
                </p>
              </div>
              <Button size="sm" variant="outline" asChild>
                <a href="/metrics" target="_blank" rel="noreferrer">
                  Open /metrics
                </a>
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

