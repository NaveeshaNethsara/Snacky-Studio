import { Check, RotateCcw, X, ArrowDownToLine } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { labels, remaining, size } from '@/lib/tasks';
import { terminal, type Task } from '@/types';

interface Props { tasks: Task[]; wanted: Set<string>; onCancel: (id: string) => void; onRetry: (task: Task) => void; onSave: (task: Task) => void; onHide: (id: string) => void; onAnother: () => void; busy: boolean }
export function TaskList({tasks, wanted, onCancel, onRetry, onSave, onHide, onAnother, busy}: Props) {
  if (!tasks.length) return null;
  const active = tasks.filter(t => !terminal.has(t.status)).length;
  return <section className="downloads-section" aria-labelledby="downloads-title"><div className="section-heading"><div><h2 id="downloads-title">Your downloads</h2>{active > 0 && <span className="count-badge">{active} active</span>}</div><Button variant="ghost" size="sm" onClick={onAnother}>Download another</Button></div>
    <div className="task-list">{tasks.map(task => {
      const done = terminal.has(task.status);
      const detail = [task.total_bytes && task.status === 'downloading' ? `${task.progress}% · ${size(task.downloaded_bytes)} / ${size(task.total_bytes)}` : '',
        task.status === 'downloading' ? task.speed : '', task.status === 'downloading' ? remaining(task.eta) : '', task.managed_here === false ? 'Continuing in the previous window' : ''].filter(Boolean).join(' · ');
      return <article className={`task-row ${task.status}`} key={task.id}>
        <div className="task-icon">{task.status === 'completed' ? <Check size={18}/> : <ArrowDownToLine size={18}/>}</div>
        <div className="task-copy"><h3 title={task.title}>{task.title || 'Your media'}</h3><span className="task-status">{task.format === 'slideshow' ? 'SLIDESHOW' : task.format.toUpperCase()} · {task.status === 'downloading' && task.detail ? task.detail : labels[task.status]}</span>
          {!done && <><Progress aria-label={`Preparation progress for ${task.title || 'download'}`} value={task.status === 'downloading' && task.total_bytes ? Math.min(99,task.progress) : null}/><p className="task-detail">{detail || task.detail || 'Preparing your file'}</p></>}
          {task.error && <p className="task-error">{task.error}</p>}
        </div><div className="task-actions">
          {task.status === 'completed' ? <Button variant="outline" size="sm" onClick={() => onSave(task)}>Save again</Button>
            : done ? <Button variant="outline" size="sm" disabled={busy} onClick={() => onRetry(task)}><RotateCcw size={13}/>Retry</Button>
            : !wanted.has(task.id) && <Button variant="outline" size="sm" onClick={() => onSave(task)}>Save when ready</Button>}
          {!done && task.managed_here !== false && <Button variant="ghost" size="sm" disabled={task.status === 'cancelling'} onClick={() => onCancel(task.id)}>Cancel</Button>}
          {done && <Button variant="ghost" size="icon" aria-label={`Hide download ${task.title}`} onClick={() => onHide(task.id)}><X size={15}/></Button>}
        </div></article>;
    })}</div>
  </section>;
}
