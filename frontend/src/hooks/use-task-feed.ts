import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type { Task } from '@/types';

export function useTaskFeed(enabled: boolean, onTasks: (tasks: Task[]) => void, onExpired: () => void) {
  const callback = useRef(onTasks), expired = useRef(onExpired);
  callback.current = onTasks; expired.current = onExpired;
  const [connection, setConnection] = useState<'connected' | 'reconnecting'>('connected');
  useEffect(() => {
    if (!enabled) return;
    let disposed = false, source: EventSource | null = null;
    let polling = false, inFlight = false, timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    async function poll() {
      if (disposed || inFlight) return;
      inFlight = true;
      const request = new AbortController(); controller = request;
      const timeout = setTimeout(() => request.abort(), 10000);
      try {
        const result = await api<{tasks: Task[]}>('/api/tasks', { signal: request.signal });
        if (!disposed) { callback.current(result.tasks); setConnection('connected'); }
      } catch (error) {
        if (!disposed && error instanceof ApiError && error.status === 401) { expired.current(); return; }
        if (!disposed) setConnection('reconnecting');
      } finally { clearTimeout(timeout); inFlight = false; }
      if (!disposed && polling) timer = setTimeout(poll, 1500);
    }
    function fallback() {
      if (disposed || polling) return;
      source?.close(); polling = true; setConnection('reconnecting'); void poll();
    }
    void poll();
    if (typeof EventSource !== 'undefined') {
      source = new EventSource('/api/stream-tasks');
      source.onopen = () => { if (!disposed) setConnection('connected'); };
      source.onmessage = event => {
        if (disposed) return;
        try { callback.current((JSON.parse(event.data) as {tasks: Task[]}).tasks); } catch { fallback(); }
      };
      source.onerror = fallback;
    } else fallback();
    return () => { disposed = true; source?.close(); clearTimeout(timer); controller?.abort(); };
  }, [enabled]);
  return connection;
}
