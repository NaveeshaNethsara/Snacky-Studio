import type { Task } from '@/types';
import { terminal } from '@/types';

export const labels: Record<Task['status'], string> = {
  queued: 'In queue', fetching_info: 'Checking your link', downloading: 'Downloading', processing: 'Converting',
  finishing: 'Finishing up', cancelling: 'Cancelling', cancelled: 'Cancelled', interrupted: 'Interrupted', completed: 'Ready to save', error: 'Failed',
};
export function mergeTasks(previous: Task[], snapshots: Task[]): Task[] {
  const merged = new Map(previous.map(task => [task.id, task]));
  for (const task of snapshots) {
    const before = merged.get(task.id);
    if (!before || task.updated_at >= before.updated_at) merged.set(task.id, task);
  }
  const all = [...merged.values()];
  return [...all.filter(task => !terminal.has(task.status)), ...all.filter(task => terminal.has(task.status)).sort((a,b) => b.created_at - a.created_at).slice(0, 10)]
    .sort((a,b) => b.created_at - a.created_at);
}
export function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
export function remaining(eta: string) {
  if (!/^\d+s$/.test(eta)) return '';
  const seconds = Number(eta.slice(0, -1));
  return seconds >= 3600 ? `${Math.floor(seconds/3600)}h ${Math.ceil((seconds%3600)/60)}m left`
    : seconds >= 60 ? `${Math.ceil(seconds/60)}m left` : `${seconds}s left`;
}
export function pendingSaves() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem('snacky.browserWanted') || '[]');
    return new Set<string>(Array.isArray(parsed) ? parsed.filter(id => typeof id === 'string' && /^[a-f\d-]{36}$/i.test(id)) : []);
  } catch { return new Set<string>(); }
}
export function persistSaves(ids: Set<string>) {
  try { sessionStorage.setItem('snacky.browserWanted', JSON.stringify([...ids])); } catch { /* Session storage is optional. */ }
}
