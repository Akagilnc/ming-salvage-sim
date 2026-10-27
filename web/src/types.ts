export interface Entity {
  id: string;
  kind: string;
  key: string;
  source: string;
  data: Record<string, unknown>;
}
export interface Fact {
  entity_id: string;
  kind: string;
  emperor_words: string;
  detail: Record<string, unknown>;
}
export interface Records { entities: Entity[]; facts: Fact[] }
export type TextUpdate = string | { replace: string };
export interface Turn { id: string; emperor_words: string; scene: string }
export interface Night { id: string; closed: boolean; hall: string[]; turns: Turn[]; result: 'translated' | 'unhandled' | null }
export interface Interaction { action: string; status: string; payload: { words?: string; log?: string; type?: string } }
export interface Petition { id: string; text: string; options: string[]; blocking: boolean; signer?: string | null; target?: string | null; revision_of?: string | null }
export interface Settings { backend: '' | 'api' | 'claude-cli' | 'codex' | 'grok' | 'pi'; model: string; base_url: string; api_key: string; effort: string }
export interface Configuration extends Settings { month_model: Settings | null }
export interface Snapshot {
  saves: string[];
  save: string | null;
  settings: Configuration;
  required_settings: Partial<Record<Settings['backend'], (keyof Settings)[]>>;
  game: null | {
    face: 'desk' | 'audience' | 'month';
    date: { year: number; month: number };
    night: Night | null;
    running: boolean;
    failure: Interaction | null;
    pending: Interaction | null;
    unhandled_monthly: { entity_id: string }[];
    petitions: Petition[];
    returned_petitions: { petition: Petition; awaiting_drafter: boolean }[];
  };
}
export interface Action {
  action: 'new' | 'load' | 'continue' | 'menu' | 'settings' | 'open' | 'say' | 'dismiss' | 'month' | 'choose' | 'retry';
  save?: string;
  words?: string;
  petition?: string;
  option?: number;
  settings?: Configuration;
}
