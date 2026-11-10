import { useState, useEffect } from 'react';
import { Settings2, Moon, Sun, Monitor, Globe, Check } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { useTranslation, Language } from '@/lib/i18n';

export interface UserPreferencesData {
  default_format: 'mp4' | 'mp3' | 'photos' | 'slideshow';
  default_quality: string;
  default_audio_bitrate: string;
  theme: 'system' | 'dark' | 'light';
  language: Language;
  auto_download: boolean;
}

const DEFAULT_PREFERENCES: UserPreferencesData = {
  default_format: 'mp4',
  default_quality: 'best',
  default_audio_bitrate: '320',
  theme: 'system',
  language: 'en',
  auto_download: true,
};

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPreferencesChanged?: (prefs: UserPreferencesData) => void;
}

export function PreferencesModal({ open, onOpenChange, onPreferencesChanged }: Props) {
  const { t, language, setLanguage } = useTranslation();
  const [prefs, setPrefs] = useState<UserPreferencesData>(() => {
    try {
      const cached = localStorage.getItem('snacky_preferences');
      if (cached) return { ...DEFAULT_PREFERENCES, ...JSON.parse(cached), language };
    } catch {
      // Fallback
    }
    return { ...DEFAULT_PREFERENCES, language };
  });
  const [saving, setSaving] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  // Load preferences from API on open
  useEffect(() => {
    if (!open) return;
    setSavedSuccess(false);
    void api<UserPreferencesData>('/api/preferences')
      .then((data) => {
        setPrefs((current) => ({ ...current, ...data }));
        if (data.theme) applyTheme(data.theme);
        if (data.language) setLanguage(data.language);
      })
      .catch(() => {
        // Fallback to localStorage
      });
  }, [open, setLanguage]);

  const applyTheme = (theme: 'system' | 'dark' | 'light') => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
      root.classList.remove('light');
    } else if (theme === 'light') {
      root.classList.add('light');
      root.classList.remove('dark');
    } else {
      // System default
      root.classList.remove('dark', 'light');
      if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        root.classList.add('dark');
      }
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      applyTheme(prefs.theme);
      setLanguage(prefs.language);
      localStorage.setItem('snacky_preferences', JSON.stringify(prefs));
      localStorage.setItem('snacky_theme', prefs.theme);

      await api('/api/preferences', {
        method: 'PUT',
        body: prefs,
      }).catch(() => {});

      setSavedSuccess(true);
      onPreferencesChanged?.(prefs);
      setTimeout(() => {
        onOpenChange(false);
        setSavedSuccess(false);
      }, 700);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" aria-describedby="pref-desc">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Settings2 className="text-pink-500" size={20} />
            <DialogTitle>{t('prefTitle')}</DialogTitle>
          </div>
          <DialogDescription id="pref-desc">{t('prefDesc')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2 text-sm">
          {/* Appearance Theme */}
          <div>
            <label className="font-medium text-xs uppercase tracking-wider text-muted-foreground block mb-1.5">
              {t('themeLabel')}
            </label>
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label={t('themeLabel')}>
              {[
                { id: 'system', label: t('themeSystem'), icon: Monitor },
                { id: 'dark', label: t('themeDark'), icon: Moon },
                { id: 'light', label: t('themeLight'), icon: Sun },
              ].map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  role="radio"
                  aria-checked={prefs.theme === id}
                  onClick={() => setPrefs({ ...prefs, theme: id as any })}
                  className={`flex items-center justify-center gap-2 py-2 px-3 rounded-lg border text-xs font-medium transition-all ${
                    prefs.theme === id
                      ? 'border-pink-500 bg-pink-500/10 text-pink-400 font-semibold shadow-sm'
                      : 'border-border/60 hover:bg-muted/50 text-muted-foreground'
                  }`}
                >
                  <Icon size={14} />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Language Selection */}
          <div>
            <label className="font-medium text-xs uppercase tracking-wider text-muted-foreground block mb-1.5">
              {t('langLabel')}
            </label>
            <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label={t('langLabel')}>
              {[
                { id: 'en', label: 'English (US)' },
                { id: 'es', label: 'Español' },
              ].map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="radio"
                  aria-checked={prefs.language === id}
                  onClick={() => setPrefs({ ...prefs, language: id as Language })}
                  className={`flex items-center justify-center gap-2 py-2 px-3 rounded-lg border text-xs font-medium transition-all ${
                    prefs.language === id
                      ? 'border-pink-500 bg-pink-500/10 text-pink-400 font-semibold shadow-sm'
                      : 'border-border/60 hover:bg-muted/50 text-muted-foreground'
                  }`}
                >
                  <Globe size={13} />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Default Media Format */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="pref-default-format" className="font-medium text-xs uppercase tracking-wider text-muted-foreground block mb-1.5">
                {t('defaultFormatLabel')}
              </label>
              <select
                id="pref-default-format"
                value={prefs.default_format}
                onChange={(e) => setPrefs({ ...prefs, default_format: e.target.value as any })}
                className="w-full bg-background border border-border/70 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-pink-500 outline-none"
              >
                <option value="mp4">Video (MP4)</option>
                <option value="mp3">Audio (MP3)</option>
                <option value="photos">Photos (ZIP)</option>
                <option value="slideshow">TikTok Slideshow</option>
              </select>
            </div>

            {/* Default Quality / Bitrate */}
            <div>
              <label htmlFor="pref-default-quality" className="font-medium text-xs uppercase tracking-wider text-muted-foreground block mb-1.5">
                {prefs.default_format === 'mp3' ? t('defaultBitrateLabel') : t('defaultQualityLabel')}
              </label>
              {prefs.default_format === 'mp3' ? (
                <select
                  id="pref-default-quality"
                  value={prefs.default_audio_bitrate}
                  onChange={(e) => setPrefs({ ...prefs, default_audio_bitrate: e.target.value })}
                  className="w-full bg-background border border-border/70 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-pink-500 outline-none"
                >
                  <option value="320">320 kbps (High Fidelity)</option>
                  <option value="256">256 kbps (Standard)</option>
                  <option value="192">192 kbps</option>
                  <option value="128">128 kbps (Compact)</option>
                </select>
              ) : (
                <select
                  id="pref-default-quality"
                  value={prefs.default_quality}
                  onChange={(e) => setPrefs({ ...prefs, default_quality: e.target.value })}
                  className="w-full bg-background border border-border/70 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-pink-500 outline-none"
                >
                  <option value="best">Best Available</option>
                  <option value="1080">1080p FHD</option>
                  <option value="720">720p HD</option>
                  <option value="480">480p SD</option>
                </select>
              )}
            </div>
          </div>

          {/* Auto Download Checkbox */}
          <div className="flex items-center gap-2.5 pt-1">
            <input
              type="checkbox"
              id="pref-auto-save"
              checked={prefs.auto_download}
              onChange={(e) => setPrefs({ ...prefs, auto_download: e.target.checked })}
              className="h-4 w-4 rounded border-border text-pink-500 focus:ring-pink-500 accent-pink-500 cursor-pointer"
            />
            <label htmlFor="pref-auto-save" className="text-xs text-muted-foreground cursor-pointer select-none">
              {t('autoSaveLabel')}
            </label>
          </div>
        </div>

        <DialogFooter className="flex items-center justify-between gap-2 pt-2">
          {savedSuccess && (
            <span className="text-xs text-emerald-400 flex items-center gap-1 font-medium animate-pulse">
              <Check size={14} /> {t('prefSavedNotice')}
            </span>
          )}
          <div className="flex gap-2 ml-auto">
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              {t('keepFile')}
            </Button>
            <Button
              className="gradient-button"
              size="sm"
              disabled={saving}
              onClick={() => void handleSave()}
            >
              {saving ? t('batchProcessingBtn') : t('savePreferencesBtn')}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

