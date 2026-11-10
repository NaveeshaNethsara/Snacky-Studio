import { useMemo, useState } from 'react';
import { ArrowDownToLine, Film, ImageIcon, Music2, Search, RefreshCw, Trash2, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { MediaFile } from '@/types';
import { useTranslation } from '@/lib/i18n';

interface Props {
  files: MediaFile[];
  loading: boolean;
  onRefresh: () => void;
  onSave: (file: MediaFile) => void;
  onDelete: (file: MediaFile) => void;
}

type SortField = 'date' | 'size' | 'name';
type SortOrder = 'desc' | 'asc';

export function Library({ files, loading, onRefresh, onSave, onDelete }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [filter, setFilter] = useState<'all' | 'video' | 'audio' | 'photos'>('all');
  const [query, setQuery] = useState('');
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');

  // Filtered & Sorted files
  const visible = useMemo(() => {
    return files
      .filter((file) => {
        const matchesKind = filter === 'all' || file.kind === filter;
        const matchesQuery =
          !query ||
          file.filename.toLowerCase().includes(query.toLowerCase()) ||
          file.format.toLowerCase().includes(query.toLowerCase());
        return matchesKind && matchesQuery;
      })
      .sort((a, b) => {
        let diff = 0;
        if (sortField === 'date') {
          diff = a.created_at - b.created_at;
        } else if (sortField === 'size') {
          diff = a.size_bytes - b.size_bytes;
        } else if (sortField === 'name') {
          diff = a.filename.localeCompare(b.filename);
        }
        return sortOrder === 'desc' ? -diff : diff;
      });
  }, [files, filter, query, sortField, sortOrder]);

  const totalBytes = files.reduce((sum, file) => sum + file.size_bytes, 0);

  const toggleSortOrder = () => {
    setSortOrder((current) => (current === 'desc' ? 'asc' : 'desc'));
  };

  return (
    <section className="library-section" aria-labelledby="library-title">
      <div className="section-heading">
        <h2 id="library-title">{t('libraryTitle')}</h2>
        <div className="flex items-center gap-1.5">
          {files.length > 3 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setExpanded(!expanded)}
              aria-expanded={expanded}
            >
              {expanded ? t('showLess') : t('viewAll', { count: files.length })}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('refreshDownloads')}
            disabled={loading}
            onClick={onRefresh}
          >
            <RefreshCw className={loading ? 'spin' : ''} size={16} />
          </Button>
        </div>
      </div>

      {expanded && (
        <div className="library-toolbar flex flex-col gap-2.5 pb-2">
          {/* Top row: Filter Pills & Search */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div role="group" aria-label="Filter media by type" className="flex gap-1">
              {(['all', 'video', 'audio', 'photos'] as const).map((kind) => {
                const labelKey = kind === 'all' ? 'filterAll' : kind === 'video' ? 'filterVideo' : kind === 'audio' ? 'filterAudio' : 'filterPhotos';
                return (
                  <Button
                    key={kind}
                    variant={filter === kind ? 'secondary' : 'ghost'}
                    size="sm"
                    aria-pressed={filter === kind}
                    onClick={() => setFilter(kind)}
                  >
                    {t(labelKey)}
                  </Button>
                );
              })}
            </div>

            <div className="search-input relative flex-1 min-w-[200px]">
              <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              <Input
                placeholder={t('searchFiles')}
                aria-label={t('searchFiles')}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-8 text-xs h-8"
              />
            </div>
          </div>

          {/* Bottom row: Multi-field Sort Controls */}
          <div className="flex items-center justify-between text-xs text-muted-foreground pt-1 border-t border-border/40">
            <div className="flex items-center gap-2">
              <span className="font-medium flex items-center gap-1">
                <ArrowUpDown size={12} /> {t('sortLabel')}:
              </span>
              <div className="flex gap-1" role="radiogroup" aria-label="Sort files by">
                {[
                  { field: 'date', label: sortOrder === 'desc' ? t('sortNewest') : t('sortOldest') },
                  { field: 'size', label: sortOrder === 'desc' ? t('sortLargest') : t('sortSmallest') },
                  { field: 'name', label: sortOrder === 'desc' ? t('sortNameDesc') : t('sortNameAsc') },
                ].map(({ field, label }) => (
                  <button
                    key={field}
                    type="button"
                    role="radio"
                    aria-checked={sortField === field}
                    onClick={() => {
                      if (sortField === field) toggleSortOrder();
                      else setSortField(field as SortField);
                    }}
                    className={`px-2 py-0.5 rounded text-xs transition-colors flex items-center gap-1 ${sortField === field
                        ? 'bg-secondary text-foreground font-semibold shadow-xs'
                        : 'hover:text-foreground'
                      }`}
                  >
                    <span>{label}</span>
                    {sortField === field && (
                      sortOrder === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />
                    )}
                  </button>
                ))}
              </div>
            </div>

            <span className="text-[11px] opacity-75">
              {visible.length} {visible.length === 1 ? 'file' : 'files'}
            </span>
          </div>
        </div>
      )}

      {/* Media Rows */}
      <div className="library-list">
        {(expanded ? visible : files.slice(0, 3)).map((file) => {
          const Icon = file.kind === 'photos' ? ImageIcon : file.kind === 'audio' ? Music2 : Film;
          const title = file.filename.replace(/ \[[a-f\d-]{36}\](?=\.)/i, '');
          return (
            <article className="library-row" key={file.filename}>
              <div className={`file-icon ${file.kind}`}>
                <Icon size={19} />
              </div>
              <div className="file-copy">
                <h3 title={file.filename}>{title}</h3>
                <p>
                  {file.format} · {file.size}
                </p>
              </div>
              <time dateTime={new Date(file.created_at * 1000).toISOString()}>
                {new Date(file.created_at * 1000).toLocaleDateString(undefined, {
                  month: 'short',
                  day: 'numeric',
                })}
              </time>
              <Button
                variant="outline"
                size="sm"
                aria-label={`Save ${title}`}
                onClick={() => onSave(file)}
              >
                <ArrowDownToLine size={14} />
                <span className="save-label">{t('saveBtn')}</span>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${title}`}
                onClick={() => onDelete(file)}
              >
                <Trash2 size={15} />
              </Button>
            </article>
          );
        })}

        {!files.length && (
          <div className="empty-library">
            <ArrowDownToLine size={23} />
            <p>{t('emptyLibrary')}</p>
          </div>
        )}

        {expanded && files.length > 0 && !visible.length && (
          <p className="empty-library">{t('noMatchingFiles')}</p>
        )}
      </div>

      {!!files.length && (
        <p className="quiet-note">
          {t('libraryStats', {
            count: files.length,
            size: (totalBytes / 1024 ** 3).toFixed(2),
          })}
        </p>
      )}
    </section>
  );
}
