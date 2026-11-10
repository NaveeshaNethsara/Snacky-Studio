import { useState, useMemo } from 'react';
import { Layers, ArrowRight, X, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { useTranslation } from '@/lib/i18n';
import type { Format, Task } from '@/types';

interface Props {
  defaultFormat?: Format;
  defaultQuality?: string;
  busy: boolean;
  onBatchStarted: (tasks: Task[], batchId: string) => void;
  onError: (error: Error) => void;
}

export function BatchDownloader({ defaultFormat = 'mp4', defaultQuality = 'best', busy, onBatchStarted, onError }: Props) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [format, setFormat] = useState<Format>(defaultFormat);
  const [quality, setQuality] = useState<string>(defaultQuality);
  const [submitting, setSubmitting] = useState(false);

  // Parse lines into clean URLs
  const urls = useMemo(() => {
    return text
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0 && /^https?:\/\//i.test(line));
  }, [text]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!urls.length || submitting || busy) return;

    setSubmitting(true);
    try {
      const response = await api<{
        batch_id: string;
        total: number;
        submitted: number;
        failed: number;
        tasks: Task[];
        errors: { url: string; error: string }[];
      }>('/api/batch', {
        method: 'POST',
        body: {
          urls,
          format,
          quality,
        },
      });

      if (response.tasks.length > 0) {
        onBatchStarted(response.tasks, response.batch_id);
        setText('');
      } else if (response.errors.length > 0) {
        onError(new Error(response.errors[0].error));
      }
    } catch (err) {
      onError(err instanceof Error ? err : new Error('Batch submission failed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3.5 pt-1" aria-label="Batch media downloader">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label htmlFor="batch-urls-input" className="text-xs font-medium text-muted-foreground">
            {t('batchInputLabel')}
          </label>
          {text.trim() && (
            <button
              type="button"
              onClick={() => setText('')}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 cursor-pointer"
              aria-label={t('clearBtn')}
            >
              <X size={12} /> {t('clearBtn')}
            </button>
          )}
        </div>

        <textarea
          id="batch-urls-input"
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('batchPlaceholder')}
          className="w-full bg-background/80 border border-border/80 rounded-xl p-3 text-xs font-mono focus:ring-1 focus:ring-pink-500 focus:border-pink-500 outline-none resize-y min-h-[90px]"
          required
        />

        <div className="flex items-center justify-between text-xs text-muted-foreground pt-0.5">
          <span className="flex items-center gap-1 font-medium">
            <Layers size={13} className="text-pink-400" />
            {t('batchCount', { count: urls.length })}
          </span>
          <span className="text-[11px] opacity-75">Max 50 URLs per batch</span>
        </div>
      </div>

      {/* Format & Quality Pickers */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-card/60 border border-border/60">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label htmlFor="batch-format-select" className="text-xs font-medium text-muted-foreground">
              {t('formatSelect')}:
            </label>
            <select
              id="batch-format-select"
              value={format}
              onChange={(e) => setFormat(e.target.value as Format)}
              className="bg-background border border-border/70 rounded-md px-2 py-1 text-xs focus:ring-1 focus:ring-pink-500 outline-none"
            >
              <option value="mp4">Video (MP4)</option>
              <option value="mp3">Audio (MP3)</option>
              <option value="photos">Photos (ZIP)</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <label htmlFor="batch-quality-select" className="text-xs font-medium text-muted-foreground">
              {t('qualitySelect')}:
            </label>
            {format === 'mp3' ? (
              <select
                id="batch-quality-select"
                value={quality}
                onChange={(e) => setQuality(e.target.value)}
                className="bg-background border border-border/70 rounded-md px-2 py-1 text-xs focus:ring-1 focus:ring-pink-500 outline-none"
              >
                <option value="320">320 kbps</option>
                <option value="256">256 kbps</option>
                <option value="128">128 kbps</option>
              </select>
            ) : (
              <select
                id="batch-quality-select"
                value={quality}
                onChange={(e) => setQuality(e.target.value)}
                className="bg-background border border-border/70 rounded-md px-2 py-1 text-xs focus:ring-1 focus:ring-pink-500 outline-none"
              >
                <option value="best">Best Available</option>
                <option value="1080">1080p</option>
                <option value="720">720p</option>
                <option value="480">480p</option>
              </select>
            )}
          </div>
        </div>

        <Button
          type="submit"
          className="gradient-button ml-auto"
          size="sm"
          disabled={!urls.length || submitting || busy}
        >
          {submitting ? (
            t('batchProcessingBtn')
          ) : (
            <>
              <span>{t('batchStartBtn')}</span>
              <ArrowRight size={14} />
            </>
          )}
        </Button>
      </div>

      {urls.length === 0 && text.trim().length > 0 && (
        <div className="text-amber-400 text-xs flex items-center gap-1.5 pt-1">
          <AlertCircle size={14} />
          <span>No valid HTTP/HTTPS media URLs found. Ensure each URL starts with http:// or https://</span>
        </div>
      )}
    </form>
  );
}

