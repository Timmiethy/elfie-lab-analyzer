/**
 * Qwen chat client stub.
 *
 * Real impl missing from merge. This stub keeps the UI compiling and
 * gracefully disables the chat until a proper backend-proxied endpoint
 * is wired up (never expose VLM API key to browser).
 */

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface QwenChatOptions {
  historyContext?: string;
  signal?: AbortSignal;
}

export function isQwenConfigured(): boolean {
  // Disabled until a server-side /api/chat endpoint exists.
  return false;
}

export async function qwenChat(
  _messages: ChatMessage[],
  _options?: QwenChatOptions,
): Promise<string> {
  throw new Error('chat_not_configured');
}
