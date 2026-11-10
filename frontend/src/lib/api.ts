export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const response = await fetch(path, {
    method: options.method || 'GET', credentials: 'same-origin', signal: options.signal,
    headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((item: { msg: string }) => item.msg).join(' ') : data.detail;
    throw new ApiError(typeof detail === 'string' ? detail : 'The request could not be completed.', response.status);
  }
  return data as T;
}

export function safeImage(url?: string | null) {
  if (!url) return undefined;
  try {
    const parsed = new URL(url, window.location.origin);
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : undefined;
  } catch { return undefined; }
}

export async function saveFile(url: string, filename = '') {
  // Desktop uses the default browser's download manager for the local attachment.
  if ('__TAURI_INTERNALS__' in window) {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('open_download', { path: url });
    return;
  }
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.hidden = true;
  document.body.append(link); link.click(); link.remove();
}
