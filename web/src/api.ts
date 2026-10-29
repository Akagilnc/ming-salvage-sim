import type { Action, Records, Snapshot } from './types';

type ActionResult = Partial<Pick<Snapshot, 'save' | 'navigation'>>;

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}
export const records = () => api<Records>('/records');
export async function act(action: Action): Promise<ActionResult> {
  const response = await fetch('/actions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(action),
  });
  if (!response.ok) throw new Error(await response.text());
  // Actions without a response body return 204; /stream supplies their state.
  return response.status === 200 ? await response.json() as ActionResult : {};
}
