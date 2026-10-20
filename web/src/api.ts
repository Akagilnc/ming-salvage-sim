import type { Action, Records, Snapshot } from './types';

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}
export const state = () => api<Snapshot>('/state');
export const records = () => api<Records>('/records');
export async function act(action: Action): Promise<void> {
  const response = await fetch('/actions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(action),
  });
  if (!response.ok) throw new Error(await response.text());
  // SSE delivery is independent of this request; EventSource receives increments.
  await response.text();
}
