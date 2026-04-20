/**
 * Qwen chat client — calls the backend `/api/chat/completions` proxy.
 *
 * Why this is a server proxy: the previous frontend wired DashScope directly
 * with `VITE_QWEN_API_KEY`, which exposed the secret in the browser bundle.
 * The key now lives only on the backend (`ELFIE_QWEN_API_KEY`); this client
 * just sends the chat transcript to our own server.
 */

import { supabase } from '../lib/supabase';

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface QwenChatOptions {
  historyContext?: string;
  signal?: AbortSignal;
}

const API_ORIGIN = (
  (typeof import.meta !== 'undefined' ? import.meta.env?.VITE_API_URL : '') || ''
).replace(/\/+$/, '');
const BASE_URL = API_ORIGIN ? `${API_ORIGIN}/api` : '/api';

/** Capability check. The backend owns the key, so as long as the proxy URL
 *  is reachable the chat is "configured". We treat it as always-on at the
 *  client level; the backend will return a clear error if it isn't ready. */
export function isQwenConfigured(): boolean {
  return true;
}

async function authHeaders(): Promise<Record<string, string>> {
  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session?.access_token) return {};
    return { Authorization: `Bearer ${session.access_token}` };
  } catch {
    return {};
  }
}

interface ChatBackendResponse {
  reply: string;
  correlation_id?: string;
}

export async function qwenChat(
  messages: ChatMessage[],
  options?: QwenChatOptions,
): Promise<string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(await authHeaders()),
  };

  const body = JSON.stringify({
    messages,
    history_context: options?.historyContext ?? null,
  });

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/chat/completions`, {
      method: 'POST',
      headers,
      body,
      signal: options?.signal,
    });
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError') throw err;
    throw new Error('chat_network_error');
  }

  if (response.status === 401) throw new Error('chat_unauthorized');
  if (response.status === 429) throw new Error('chat_rate_limited');
  if (response.status === 422) throw new Error('chat_invalid_request');
  if (!response.ok) throw new Error('chat_upstream_error');

  let data: ChatBackendResponse;
  try {
    data = (await response.json()) as ChatBackendResponse;
  } catch {
    throw new Error('chat_parse_error');
  }

  if (typeof data?.reply !== 'string' || !data.reply.trim()) {
    throw new Error('chat_empty_reply');
  }
  return data.reply;
}
