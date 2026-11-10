import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Clipboard, Cloud, Folder, Globe, Link2, LockKeyhole, Settings2, ShieldCheck, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { api, ApiError, saveFile } from '@/lib/api';
import { mergeTasks, pendingSaves, persistSaves } from '@/lib/tasks';
import { useTaskFeed } from '@/hooks/use-task-feed';
import { MediaPreview } from '@/components/MediaPreview';
import { TaskList } from '@/components/TaskList';
import { Library } from '@/components/Library';
import { AdminConsole } from '@/components/AdminConsole';
import { BatchDownloader } from '@/components/BatchDownloader';
import { PreferencesModal, type UserPreferencesData } from '@/components/PreferencesModal';
import { useTranslation } from '@/lib/i18n';
import { terminal, type DownloadPayload, type Format, type MediaFile, type MediaInfo, type Session, type Task } from '@/types';

export default function App() {
  const { t, language, setLanguage } = useTranslation();
  const [session, setSession] = useState<Session | null>(null);
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [mfaPrompt, setMfaPrompt] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [prefOpen, setPrefOpen] = useState(false);
  const [userPrefs, setUserPrefs] = useState<UserPreferencesData | null>(null);

  // Downloader Mode: Single Link or Batch Links
  const [activeTab, setActiveTab] = useState<'single' | 'batch'>('single');

  const [url, setUrl] = useState('');
  const [info, setInfo] = useState<MediaInfo | null>(null);
  const [format, setFormat] = useState<Format>('mp4');
  const [quality, setQuality] = useState('best');
  const [analyzing, setAnalyzing] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [tasks, setTasks] = useState<Task[]>([]);
  const [files, setFiles] = useState<MediaFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<MediaFile | null>(null);
  const [help, setHelp] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const input = useRef<HTMLInputElement>(null);
  const analysis = useRef<AbortController | null>(null);
  const wanted = useRef(pendingSaves());
  const delivered = useRef(new Set<string>());
  const hidden = useRef(new Set<string>());
  const latest = useRef<Task[]>([]);
  const starting = useRef(false);
  const [, force] = useState(0);

  const report = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) {
      setSession((current) => (current ? { ...current, authenticated: false } : null));
    }
    setNotice({
      text: error instanceof Error ? error.message : 'Something went wrong. Please try again.',
      error: true,
    });
  }, []);

  const loadFiles = useCallback(async () => {
    setLoading(true);
    try {
      setFiles((await api<{ files: MediaFile[] }>('/api/history')).files);
    } catch (error) {
      report(error);
    } finally {
      setLoading(false);
    }
  }, [report]);

  const acceptTasks = useCallback(
    (snapshots: Task[]) => {
      const merged = mergeTasks(latest.current, snapshots).filter((task) => !hidden.current.has(task.id));
      for (const task of merged) {
        if (!wanted.current.has(task.id) || !terminal.has(task.status)) continue;
        if (task.status === 'completed' && !delivered.current.has(task.id)) {
          delivered.current.add(task.id);
          wanted.current.delete(task.id);
          persistSaves(wanted.current);
          void saveFile(`/api/browser-download/${task.id}`, task.filename).catch((error) => {
            delivered.current.delete(task.id);
            report(error);
          });
        } else {
          wanted.current.delete(task.id);
          persistSaves(wanted.current);
        }
      }
      if (
        merged.some(
          (task) =>
            task.status === 'completed' &&
            latest.current.find((before) => before.id === task.id)?.status !== 'completed'
        )
      ) {
        void loadFiles();
      }
      latest.current = merged;
      setTasks(merged);
    },
    [loadFiles, report]
  );

  const connection = useTaskFeed(
    !!session?.authenticated,
    acceptTasks,
    () => setSession((current) => (current ? { ...current, authenticated: false } : null))
  );

  useEffect(() => {
    void api<Session>('/api/session').then(setSession).catch(report);
    void api<UserPreferencesData>('/api/preferences')
      .then((prefs) => {
        setUserPrefs(prefs);
        if (prefs.default_format) setFormat(prefs.default_format);
        if (prefs.default_quality) setQuality(prefs.default_quality);
      })
      .catch(() => { });
  }, [report]);

  useEffect(() => {
    if (session?.authenticated) void loadFiles();
  }, [session?.authenticated, loadFiles]);

  useEffect(() => () => analysis.current?.abort(), []);

  function editUrl(value: string) {
    analysis.current?.abort();
    analysis.current = null;
    setAnalyzing(false);
    setUrl(value);
    setInfo(null);
  }

  function chooseFormat(value: Format, data = info) {
    setFormat(value);
    const choices = value === 'mp3' ? data?.audio_qualities : data?.qualities;
    setQuality(value === 'photos' ? 'best' : choices?.[0]?.id || (value === 'mp3' ? '320' : 'best'));
  }

  async function analyze(event: React.FormEvent) {
    event.preventDefault();
    if (analyzing) return;
    const controller = new AbortController();
    analysis.current?.abort();
    analysis.current = controller;
    setAnalyzing(true);
    setInfo(null);
    setNotice(null);
    try {
      const data = await api<MediaInfo>('/api/info', {
        method: 'POST',
        body: { url: url.trim() },
        signal: controller.signal,
      });
      if (analysis.current !== controller) return;
      setInfo(data);
      chooseFormat(data.media_type === 'photos' ? 'photos' : 'mp4', data);
    } catch (error) {
      if (analysis.current === controller && !(error instanceof Error && error.name === 'AbortError')) {
        report(error);
      }
    } finally {
      if (analysis.current === controller) {
        analysis.current = null;
        setAnalyzing(false);
      }
    }
  }

  async function start(payload?: DownloadPayload) {
    if (starting.current || (!info && !payload)) return;
    starting.current = true;
    setSubmitting(true);
    setNotice(null);
    const raw = url;
    const selected = payload || { url: info!.url, title: info!.title, format, quality };
    const body = { ...selected, title: Array.from(selected.title || '').slice(0, 200).join('') };
    try {
      const result = await api<{ download_id: string; task: Task }>('/api/download', {
        method: 'POST',
        body,
      });
      wanted.current.add(result.download_id);
      persistSaves(wanted.current);
      acceptTasks([result.task]);
      setUrl((current) => (current === raw ? '' : current));
      setInfo(null);
      input.current?.focus();
      setNotice({
        text: t('downloadSuccessNotice'),
        error: false,
      });
    } catch (error) {
      report(error);
    } finally {
      starting.current = false;
      setSubmitting(false);
    }
  }

  async function saveTask(task: Task) {
    if (task.status === 'completed') {
      try {
        await saveFile(`/api/file/${task.id}`, task.filename);
      } catch (error) {
        report(error);
      }
    } else {
      wanted.current.add(task.id);
      persistSaves(wanted.current);
      force((value) => value + 1);
    }
  }

  async function cancel(id: string) {
    try {
      acceptTasks([await api<Task>(`/api/cancel/${id}`, { method: 'POST' })]);
    } catch (error) {
      report(error);
    }
  }

  async function removeFile() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api(`/api/history/${encodeURIComponent(pendingDelete.filename)}`, { method: 'DELETE' });
      setPendingDelete(null);
      await loadFiles();
    } catch (error) {
      report(error);
    } finally {
      setDeleting(false);
    }
  }

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      if (email.trim()) {
        const res = await api<{ authenticated?: boolean; mfa_required?: boolean; user?: any }>('/api/auth/login', {
          method: 'POST',
          body: { email: email.trim(), password, totp_code: totpCode || undefined },
        });
        if (res.mfa_required) {
          setMfaPrompt(true);
          setNotice({ text: 'Please enter your Two-Factor Authentication (TOTP) code.', error: false });
        } else {
          setSession({ mode: 'cloud', authenticated: true, user: res.user });
          setPassword('');
          setEmail('');
          setTotpCode('');
          setMfaPrompt(false);
          setNotice(null);
        }
      } else {
        setSession(await api<Session>('/api/session/login', { method: 'POST', body: { password } }));
        setPassword('');
        setNotice(null);
      }
    } catch (error) {
      report(error);
    } finally {
      setSubmitting(false);
    }
  }

  const visibleTasks = [
    ...tasks.filter((t) => !terminal.has(t.status)),
    ...tasks.filter((t) => terminal.has(t.status)).slice(0, 3),
  ].sort((a, b) => b.created_at - a.created_at);

  return (
    <div className="studio">
      <a className="skip-link" href="#downloader">
        {t('skipToContent')}
      </a>

      {/* Header */}
      <header className="site-header">
        <a className="brand" href="/" aria-label="Snacky Studio home">
          <img src="/static/logo_icon.png" alt="" />
          <span>
            <strong>Snacky</strong> Studio
          </span>
        </a>

        <div className="header-actions">
          {/* Workspace Badge */}
          <span className="workspace-status">
            <i />
            {session?.mode === 'cloud' ? (
              <>
                <Cloud size={13} />
                {t('privateCloud')} {session.user?.role ? `(${session.user.role})` : ''}
                {session.user?.role === 'owner' && (
                  <span className="ml-1.5 text-amber-400 font-semibold text-xs">{t('unlimitedBadge')}</span>
                )}
              </>
            ) : (
              t('localWorkspace')
            )}
          </span>

          {/* Language Switcher */}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setLanguage(language === 'en' ? 'es' : 'en')}
            className="text-xs uppercase font-semibold tracking-wider flex items-center gap-1 px-2"
            aria-label={`Switch language. Current: ${language.toUpperCase()}`}
          >
            <Globe size={13} />
            <span>{language.toUpperCase()}</span>
          </Button>

          {/* Preferences Settings Button */}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setPrefOpen(true)}
            aria-label={t('settings')}
            title={t('settings')}
          >
            <Settings2 size={16} />
          </Button>

          {session?.authenticated && (
            <>
              {session.mode === 'cloud' &&
                (session.user?.role === 'owner' || session.user?.role === 'admin') && (
                  <Button variant="outline" size="sm" onClick={() => setAdminOpen(true)}>
                    <ShieldCheck size={14} />
                    <span>{t('admin')}</span>
                  </Button>
                )}
              {session.mode === 'local' ? (
                <Button
                  variant="outline"
                  onClick={() => void api('/api/open-folder', { method: 'POST' }).catch(report)}
                >
                  <Folder size={15} />
                  <span>{t('openFolder')}</span>
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  onClick={() =>
                    void api('/api/session/logout', { method: 'POST' })
                      .then(() => {
                        setSession({ ...session, authenticated: false });
                        setTasks([]);
                        latest.current = [];
                      })
                      .catch(report)
                  }
                >
                  {t('signOut')}
                </Button>
              )}
            </>
          )}
        </div>
      </header>

      <main id="downloader">
        {/* Hero Section */}
        <section className="hero">
          <div>
            <p className="eyebrow">
              <span />
              {t('eyebrow')}
            </p>
            <h1>
              {t('heroTitle1')}
              <br />
              <span>{t('heroTitle2')}</span>
            </h1>
            <p className="hero-description">{t('heroDesc')}</p>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="art-orbit" />
            <img src="/static/logo_icon.png" alt="" />
            <span className="art-dot pink" />
            <span className="art-dot cyan" />
          </div>
        </section>

        {notice && (
          <div
            className={`notice ${notice.error ? 'error' : 'success'}`}
            role={notice.error ? 'alert' : 'status'}
          >
            <span>{notice.text}</span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Dismiss message"
              onClick={() => setNotice(null)}
            >
              <X size={15} />
            </Button>
          </div>
        )}

        {!session ? (
          <div className="input-panel">
            <p className="quiet-note">Connecting to your workspace…</p>
          </div>
        ) : !session.authenticated ? (
          <section className="input-panel login-panel">
            <LockKeyhole size={26} />
            <h2>Your private studio</h2>
            <p>
              {mfaPrompt
                ? 'Enter your 6-digit authenticator code'
                : 'Sign in with your workspace credentials'}
            </p>
            <form onSubmit={signIn} className="space-y-2">
              {!mfaPrompt ? (
                <>
                  <Input
                    type="email"
                    placeholder="Email (optional for workspace pass)"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                  <Input
                    type="password"
                    aria-label="Workspace password"
                    placeholder="Password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </>
              ) : (
                <Input
                  type="text"
                  placeholder="6-digit TOTP code"
                  maxLength={6}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  required
                />
              )}
              <Button type="submit" className="gradient-button w-full" disabled={submitting}>
                {submitting ? 'Signing in…' : mfaPrompt ? 'Verify MFA' : t('signIn')}
                <ArrowRight size={16} />
              </Button>
            </form>
          </section>
        ) : (
          <>
            {/* Input Card with Mode Tabs (Single Link vs Batch Links) */}
            <section className="input-panel">
              {/* Mode Switcher Tabs */}
              <div
                role="tablist"
                aria-label="Download mode selection"
                className="flex items-center gap-1.5 p-1 mb-3 rounded-lg bg-secondary/50 border border-border/50 max-w-fit"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'single'}
                  aria-controls="single-mode-panel"
                  id="tab-single"
                  onClick={() => setActiveTab('single')}
                  className={`px-3 py-1 rounded-md text-xs font-semibold transition-all ${activeTab === 'single'
                      ? 'bg-background text-foreground shadow-xs'
                      : 'text-muted-foreground hover:text-foreground'
                    }`}
                >
                  {t('singleMode')}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'batch'}
                  aria-controls="batch-mode-panel"
                  id="tab-batch"
                  onClick={() => setActiveTab('batch')}
                  className={`px-3 py-1 rounded-md text-xs font-semibold transition-all ${activeTab === 'batch'
                      ? 'bg-background text-foreground shadow-xs'
                      : 'text-muted-foreground hover:text-foreground'
                    }`}
                >
                  {t('batchMode')}
                </button>
              </div>

              {activeTab === 'single' ? (
                <div id="single-mode-panel" role="tabpanel" aria-labelledby="tab-single">
                  <form onSubmit={analyze}>
                    <label htmlFor="media-url">{t('singleInputLabel')}</label>
                    <div className="url-row">
                      <div className="url-field">
                        <Link2 size={19} />
                        <Input
                          ref={input}
                          id="media-url"
                          type="url"
                          placeholder={t('singlePlaceholder')}
                          value={url}
                          required
                          onChange={(e) => editUrl(e.target.value)}
                        />
                        {url ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={t('clearBtn')}
                            onClick={() => editUrl('')}
                          >
                            <X size={15} />
                          </Button>
                        ) : (
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            onClick={() =>
                              void navigator.clipboard
                                .readText()
                                .then(editUrl)
                                .catch(() =>
                                  report(
                                    new Error(
                                      'Paste the link with Ctrl+V or your browser’s paste option.'
                                    )
                                  )
                                )
                            }
                          >
                            <Clipboard size={13} />
                            {t('pasteBtn')}
                          </Button>
                        )}
                      </div>
                      <Button
                        type="submit"
                        className="gradient-button analyze-button"
                        disabled={analyzing}
                      >
                        {analyzing ? (
                          t('checkingBtn')
                        ) : /facebook\.com\/photo/i.test(url) ? (
                          t('getPhotoBtn')
                        ) : (
                          t('continueBtn')
                        )}
                        <ArrowRight size={17} />
                      </Button>
                    </div>
                    <p className="supported-platforms">
                      <span>YouTube</span>
                      <span>Instagram</span>
                      <span>TikTok</span>
                      <span>Facebook</span>
                      <span>X & more</span>
                    </p>
                  </form>

                  {info && (
                    <MediaPreview
                      info={info}
                      format={format}
                      quality={quality}
                      busy={submitting}
                      onFormat={chooseFormat}
                      onQuality={setQuality}
                      onDownload={(value) =>
                        void start(
                          value
                            ? {
                              url: info.url,
                              title: info.title,
                              format: value,
                              quality: 'best',
                            }
                            : undefined
                        )
                      }
                    />
                  )}
                </div>
              ) : (
                <div id="batch-mode-panel" role="tabpanel" aria-labelledby="tab-batch">
                  <BatchDownloader
                    busy={submitting}
                    defaultFormat={userPrefs?.default_format || 'mp4'}
                    defaultQuality={userPrefs?.default_quality || 'best'}
                    onBatchStarted={(newTasks) => {
                      acceptTasks(newTasks);
                      setNotice({
                        text: t('batchSuccessNotice', { count: newTasks.length }),
                        error: false,
                      });
                    }}
                    onError={report}
                  />
                </div>
              )}
            </section>

            {connection === 'reconnecting' && (
              <p role="status" className="quiet-note reconnecting">
                Reconnecting to live progress…
              </p>
            )}

            {/* Active & Recent Tasks */}
            <TaskList
              tasks={visibleTasks}
              wanted={wanted.current}
              busy={submitting}
              onCancel={(id) => void cancel(id)}
              onRetry={(task) =>
                void start({
                  url: task.url,
                  format: task.format,
                  quality: task.quality,
                  photo_index: task.photo_index,
                  title: task.title,
                })
              }
              onSave={(task) => void saveTask(task)}
              onHide={(id) => {
                hidden.current.add(id);
                wanted.current.delete(id);
                persistSaves(wanted.current);
                latest.current = latest.current.filter((t) => t.id !== id);
                setTasks(latest.current);
              }}
              onAnother={() => {
                editUrl('');
                input.current?.focus();
                input.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }}
            />

            {/* Library with Search, Filter & Multi-Field Sort */}
            <Library
              files={files}
              loading={loading}
              onRefresh={() => void loadFiles()}
              onSave={(file) =>
                void saveFile(
                  `/api/download-file?filename=${encodeURIComponent(file.filename)}`,
                  file.filename
                ).catch(report)
              }
              onDelete={setPendingDelete}
            />
          </>
        )}
      </main>

      {/* Footer */}
      <footer>
        <span>{session?.mode === 'cloud' ? t('cloudFooter') : t('localFooter')}</span>
        <Button variant="ghost" size="sm" onClick={() => setHelp(true)}>
          {t('howItWorks')}
        </Button>
      </footer>

      {/* How it works modal */}
      <Dialog open={help} onOpenChange={setHelp}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('howItWorksTitle')}</DialogTitle>
            <DialogDescription>{t('howItWorksDesc')}</DialogDescription>
          </DialogHeader>
          <p className="quiet-note">{t('howItWorksNote')}</p>
          <DialogFooter>
            <Button onClick={() => setHelp(false)}>{t('gotIt')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation modal */}
      <Dialog
        open={!!pendingDelete}
        onOpenChange={(open) => {
          if (!open && !deleting) setPendingDelete(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('deleteModalTitle')}</DialogTitle>
            <DialogDescription>
              {t('deleteModalDesc', { filename: pendingDelete?.filename || '' })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" disabled={deleting} onClick={() => setPendingDelete(null)}>
              {t('keepFile')}
            </Button>
            <Button variant="destructive" disabled={deleting} onClick={() => void removeFile()}>
              {deleting ? t('deletingBtn') : t('confirmDelete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Admin Console */}
      <AdminConsole open={adminOpen} onOpenChange={setAdminOpen} currentUser={session?.user} />

      {/* User Preferences Modal */}
      <PreferencesModal
        open={prefOpen}
        onOpenChange={setPrefOpen}
        onPreferencesChanged={(updated) => {
          setUserPrefs(updated);
          if (updated.default_format) setFormat(updated.default_format);
          if (updated.default_quality) setQuality(updated.default_quality);
        }}
      />
    </div>
  );
}
