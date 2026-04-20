import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { STITCH_COLORS, STITCH_RADIUS } from '../common/system';
import type { PatientArtifact } from '../../types';
import {
  addLabReportToHistory,
  buildHistoryContext,
  loadLabHistory,
  type LabHistoryEntry,
} from '../../services/labHistoryStore';
import {
  isQwenConfigured,
  qwenChat,
  type ChatMessage,
} from '../../services/qwenChat';

type Language = 'en' | 'vi';

interface Props {
  language?: Language;
  t?: (key: string) => string;
  onNavigateBack?: () => void;
  currentArtifact?: PatientArtifact | null;
}

interface UIMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  error?: boolean;
}

const COPY: Record<Language, Record<string, string>> = {
  en: {
    assistant_name: 'Elfie Coach',
    memory_none: 'No reports in memory yet',
    memory_one: '1 report in memory',
    memory_many: '{n} reports in memory',
    greeting:
      "Hi — I can answer questions about any lab report you've uploaded here, including comparing results over time. What would you like to know?",
    chip_flagged: 'What was flagged?',
    chip_trend: 'How did my results change?',
    chip_next: 'What should I do next?',
    chip_not_assessed: 'What was not assessed?',
    placeholder: 'Message Elfie Coach…',
    send_aria: 'Send message',
    back_aria: 'Back',
    thinking: 'Elfie is thinking',
    unconfigured:
      'Chat is temporarily unavailable. Please try again in a moment.',
    error_prefix: "Couldn't reach the model. ",
    footer_note: 'Wellness support only. No diagnosis or medication advice.',
  },
  vi: {
    assistant_name: 'Elfie Coach',
    memory_none: 'Chưa có báo cáo trong bộ nhớ',
    memory_one: 'Có 1 báo cáo trong bộ nhớ',
    memory_many: 'Có {n} báo cáo trong bộ nhớ',
    greeting:
      'Chào bạn — tôi có thể trả lời về các báo cáo bạn đã tải lên, kể cả so sánh giữa các lần. Bạn muốn hỏi gì?',
    chip_flagged: 'Mục nào bị đánh dấu?',
    chip_trend: 'Kết quả thay đổi thế nào?',
    chip_next: 'Tôi nên làm gì tiếp theo?',
    chip_not_assessed: 'Những gì chưa được đánh giá?',
    placeholder: 'Nhắn cho Elfie Coach…',
    send_aria: 'Gửi tin nhắn',
    back_aria: 'Quay lại',
    thinking: 'Elfie đang suy nghĩ',
    unconfigured:
      'Trò chuyện tạm thời không khả dụng. Vui lòng thử lại sau.',
    error_prefix: 'Không kết nối được mô hình. ',
    footer_note: 'Chỉ hỗ trợ sức khỏe. Không chẩn đoán hay đổi thuốc.',
  },
};

function memoryLabel(dict: Record<string, string>, n: number): string {
  if (n === 0) return dict.memory_none;
  if (n === 1) return dict.memory_one;
  return dict.memory_many.replace('{n}', String(n));
}

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const THINKING_ANIMATION_CSS = `
@keyframes elfie-thinking-bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.35; }
  40% { transform: translateY(-4px); opacity: 1; }
}
@keyframes elfie-thinking-pulse {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
@keyframes elfie-bubble-in {
  from { opacity: 0; transform: translateY(6px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.elfie-thinking-text {
  animation: elfie-thinking-pulse 1.4s ease-in-out infinite;
}
.elfie-thinking-dots {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.elfie-thinking-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: currentColor;
  display: inline-block;
  animation: elfie-thinking-bounce 1.2s ease-in-out infinite;
}
.elfie-thinking-dot:nth-child(1) { animation-delay: 0s; }
.elfie-thinking-dot:nth-child(2) { animation-delay: 0.18s; }
.elfie-thinking-dot:nth-child(3) { animation-delay: 0.36s; }
.elfie-msg-enter {
  animation: elfie-bubble-in 220ms ease-out both;
}
@media (prefers-reduced-motion: reduce) {
  .elfie-thinking-text,
  .elfie-thinking-dot,
  .elfie-msg-enter { animation: none !important; }
}
`;

/** Small circular Elfie brand avatar rendered next to assistant messages. */
function ElfieAvatar(): ReactElement {
  return (
    <span
      aria-hidden="true"
      style={{
        flexShrink: 0,
        width: 36,
        height: 36,
        borderRadius: '50%',
        backgroundColor: '#FFFFFF',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        boxShadow: '0 4px 12px rgba(255, 21, 112, 0.28)',
        border: '2px solid rgba(255, 21, 112, 0.35)',
        overflow: 'hidden',
        marginBottom: 2,
      }}
    >
      <img
        src="/elfie-bot.svg"
        alt=""
        width={32}
        height={32}
        style={{ display: 'block' }}
      />
    </span>
  );
}

/** Tiny renderer for the assistant's structured replies.
 *  Supports: one leading **bold title** line, `- ` / `* ` bullets,
 *  `## heading` lines, and inline `**bold**`. Everything else → paragraphs. */
function renderAssistantContent(content: string): ReactElement {
  const lines = content.split('\n');
  const nodes: ReactElement[] = [];
  let bulletBuffer: string[] = [];
  let keyCounter = 0;

  const flushBullets = () => {
    if (bulletBuffer.length === 0) return;
    const items = [...bulletBuffer];
    bulletBuffer = [];
    nodes.push(
      <ul
        key={`ul-${keyCounter++}`}
        style={{
          margin: '4px 0',
          paddingLeft: 18,
          display: 'flex',
          flexDirection: 'column',
          gap: 3,
        }}
      >
        {items.map((item, i) => (
          <li key={i} style={{ lineHeight: 1.5 }}>
            {renderInline(item)}
          </li>
        ))}
      </ul>,
    );
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const bulletMatch = line.match(/^\s*[-*]\s+(.*)$/);
    if (bulletMatch) {
      bulletBuffer.push(bulletMatch[1]);
      continue;
    }
    flushBullets();
    if (line.trim() === '') continue;
    const headingMatch = line.match(/^#{1,6}\s+(.*)$/);
    const fullBold = line.match(/^\*\*(.+)\*\*:?\s*$/);
    if (headingMatch || fullBold) {
      const text = (headingMatch?.[1] ?? fullBold?.[1] ?? '').trim();
      nodes.push(
        <p
          key={`h-${keyCounter++}`}
          style={{
            margin: '2px 0 4px',
            fontSize: '0.95rem',
            fontWeight: 800,
            lineHeight: 1.35,
          }}
        >
          {renderInline(text)}
        </p>,
      );
      continue;
    }
    nodes.push(
      <p
        key={`p-${keyCounter++}`}
        style={{ margin: '2px 0', lineHeight: 1.5 }}
      >
        {renderInline(line)}
      </p>,
    );
  }
  flushBullets();
  return <>{nodes}</>;
}

function renderInline(text: string): (ReactElement | string)[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    const m = part.match(/^\*\*(.+)\*\*$/);
    if (m) {
      return (
        <strong key={i} style={{ fontWeight: 700 }}>
          {m[1]}
        </strong>
      );
    }
    return part;
  });
}

export default function GuidedAsk({
  language = 'en',
  t,
  onNavigateBack,
  currentArtifact = null,
}: Props) {
  const dict = COPY[language];
  const resolve = (key: string) => {
    const translated = t?.(`guided_ask.${key}`);
    if (translated && translated !== `guided_ask.${key}`) return translated;
    return dict[key] ?? COPY.en[key] ?? key;
  };

  const [history, setHistory] = useState<LabHistoryEntry[]>(() => loadLabHistory());
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<UIMessage[]>([
    { id: 'greet', role: 'assistant', content: dict.greeting },
  ]);
  const [isSending, setIsSending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!currentArtifact) return;
    setHistory(addLabReportToHistory(currentArtifact));
  }, [currentArtifact]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isSending]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  }, [input]);

  const qwenReady = useMemo(() => isQwenConfigured(), []);
  const historyContext = useMemo(() => buildHistoryContext(history), [history]);

  const sendMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isSending) return;

    const userMsg: UIMessage = { id: makeId(), role: 'user', content: trimmed };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');

    if (!qwenReady) {
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: 'assistant',
          content: dict.unconfigured,
          error: true,
        },
      ]);
      return;
    }

    setIsSending(true);
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;

    const transcript: ChatMessage[] = messages
      .filter((m) => m.id !== 'greet' && !m.error)
      .map((m) => ({ role: m.role, content: m.content }));
    transcript.push({ role: 'user', content: trimmed });

    try {
      const reply = await qwenChat(transcript, {
        historyContext,
        signal: controller.signal,
      });
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: 'assistant', content: reply },
      ]);
    } catch (err) {
      if (controller.signal.aborted) return;
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: 'assistant',
          content: `${dict.error_prefix}${msg}`,
          error: true,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const showIntroChips = messages.length === 1;
  const chips = [
    dict.chip_flagged,
    dict.chip_trend,
    dict.chip_next,
    dict.chip_not_assessed,
  ];

  return (
    <div
      style={{
        position: 'fixed',
        top: 64,
        left: 0,
        right: 0,
        bottom: 0,
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: STITCH_COLORS.surfaceLow,
      }}
    >
      <style>{THINKING_ANIMATION_CSS}</style>

      {/* Compact header */}
      <div
        style={{
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '10px 14px',
          backgroundColor: STITCH_COLORS.surfaceWhite,
          borderBottom: `1px solid ${STITCH_COLORS.borderGhost}`,
        }}
      >
        {onNavigateBack && (
          <button
            type="button"
            onClick={onNavigateBack}
            aria-label={resolve('back_aria')}
            style={{
              width: 36,
              height: 36,
              borderRadius: STITCH_RADIUS.pill,
              border: 'none',
              backgroundColor: STITCH_COLORS.surfaceLow,
              color: STITCH_COLORS.textHeading,
              fontSize: 18,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            ‹
          </button>
        )}
        <div
          aria-hidden="true"
          style={{
            width: 40,
            height: 40,
            borderRadius: STITCH_RADIUS.pill,
            background: 'linear-gradient(135deg, #FF1570 0%, #FF7AB6 100%)',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 18,
            flexShrink: 0,
          }}
        >
          💬
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <p
            style={{
              margin: 0,
              fontSize: '0.98rem',
              fontWeight: 800,
              color: STITCH_COLORS.textHeading,
              lineHeight: 1.2,
            }}
          >
            {resolve('assistant_name')}
          </p>
          <p
            style={{
              margin: 0,
              fontSize: '0.74rem',
              color: STITCH_COLORS.textMuted,
              lineHeight: 1.2,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {memoryLabel(dict, history.length)}
          </p>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '14px 12px 8px',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        <div
          style={{
            maxWidth: 720,
            width: '100%',
            margin: '0 auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}
        >
          {messages.map((m) => {
            const isUser = m.role === 'user';
            return (
              <div
                key={m.id}
                className="elfie-msg-enter"
                style={{
                  display: 'flex',
                  justifyContent: isUser ? 'flex-end' : 'flex-start',
                  alignItems: 'flex-end',
                  gap: 8,
                }}
              >
                {!isUser && <ElfieAvatar />}
                <div
                  style={{
                    maxWidth: '86%',
                    padding: '10px 14px',
                    borderRadius: 18,
                    borderTopRightRadius: isUser ? 6 : 18,
                    borderTopLeftRadius: isUser ? 18 : 6,
                    backgroundColor: isUser
                      ? STITCH_COLORS.pink
                      : m.error
                        ? STITCH_COLORS.errorBg
                        : STITCH_COLORS.surfaceWhite,
                    color: isUser
                      ? 'white'
                      : m.error
                        ? STITCH_COLORS.errorText
                        : STITCH_COLORS.textHeading,
                    border: isUser
                      ? 'none'
                      : `1px solid ${STITCH_COLORS.borderGhost}`,
                    fontSize: '0.94rem',
                    lineHeight: 1.5,
                    wordBreak: 'break-word',
                  }}
                >
                  {isUser ? (
                    <span style={{ whiteSpace: 'pre-wrap' }}>{m.content}</span>
                  ) : (
                    renderAssistantContent(m.content)
                  )}
                </div>
              </div>
            );
          })}

          {isSending && (
            <div
              className="elfie-msg-enter"
              style={{
                display: 'flex',
                justifyContent: 'flex-start',
                alignItems: 'flex-end',
                gap: 8,
              }}
            >
              <ElfieAvatar />
              <div
                aria-live="polite"
                style={{
                  padding: '10px 14px',
                  borderRadius: 18,
                  borderTopLeftRadius: 6,
                  backgroundColor: STITCH_COLORS.surfaceWhite,
                  border: `1px solid ${STITCH_COLORS.borderGhost}`,
                  color: STITCH_COLORS.textMuted,
                  fontSize: '0.9rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                <span className="elfie-thinking-text">{dict.thinking}</span>
                <span className="elfie-thinking-dots" aria-hidden="true">
                  <span className="elfie-thinking-dot" />
                  <span className="elfie-thinking-dot" />
                  <span className="elfie-thinking-dot" />
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Suggestion chips */}
      {showIntroChips && (
        <div
          style={{
            flexShrink: 0,
            padding: '6px 10px 0',
            overflowX: 'auto',
            WebkitOverflowScrolling: 'touch',
          }}
        >
          <div
            style={{
              display: 'flex',
              gap: 8,
              paddingBottom: 6,
              width: 'max-content',
              maxWidth: '100%',
              margin: '0 auto',
            }}
          >
            {chips.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => void sendMessage(c)}
                disabled={isSending}
                style={{
                  flexShrink: 0,
                  padding: '8px 14px',
                  borderRadius: STITCH_RADIUS.pill,
                  border: `1px solid ${STITCH_COLORS.borderGhost}`,
                  backgroundColor: STITCH_COLORS.surfaceWhite,
                  color: STITCH_COLORS.textHeading,
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                  cursor: isSending ? 'not-allowed' : 'pointer',
                  opacity: isSending ? 0.6 : 1,
                }}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Composer */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void sendMessage(input);
        }}
        style={{
          flexShrink: 0,
          padding: '8px 10px calc(10px + env(safe-area-inset-bottom))',
          backgroundColor: STITCH_COLORS.surfaceWhite,
          borderTop: `1px solid ${STITCH_COLORS.borderGhost}`,
        }}
      >
        <div
          style={{
            maxWidth: 720,
            margin: '0 auto',
            display: 'flex',
            alignItems: 'flex-end',
            gap: 8,
            backgroundColor: STITCH_COLORS.surfaceLow,
            border: `1px solid ${STITCH_COLORS.borderGhost}`,
            borderRadius: 22,
            padding: '6px 6px 6px 14px',
          }}
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void sendMessage(input);
              }
            }}
            placeholder={dict.placeholder}
            rows={1}
            disabled={isSending}
            style={{
              flex: 1,
              resize: 'none',
              border: 'none',
              outline: 'none',
              backgroundColor: 'transparent',
              fontSize: '1rem',
              lineHeight: 1.4,
              padding: '8px 0',
              color: STITCH_COLORS.textHeading,
              fontFamily: 'inherit',
              maxHeight: 120,
            }}
          />
          <button
            type="submit"
            aria-label={resolve('send_aria')}
            disabled={isSending || !input.trim()}
            style={{
              flexShrink: 0,
              width: 40,
              height: 40,
              borderRadius: STITCH_RADIUS.pill,
              border: 'none',
              backgroundColor:
                isSending || !input.trim()
                  ? STITCH_COLORS.borderGhost
                  : STITCH_COLORS.pink,
              color: 'white',
              fontSize: 18,
              cursor: isSending || !input.trim() ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background-color 120ms ease',
            }}
          >
            ↑
          </button>
        </div>
        <p
          style={{
            margin: '6px 0 0',
            fontSize: '0.7rem',
            color: STITCH_COLORS.textMuted,
            textAlign: 'center',
          }}
        >
          {dict.footer_note}
        </p>
      </form>
    </div>
  );
}
