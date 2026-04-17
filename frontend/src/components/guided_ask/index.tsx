import { useMemo, useState } from 'react';
import { PageChrome, SecondaryButton, SurfaceCard } from '../common';
import { STITCH_COLORS, STITCH_RADIUS } from '../common/system';

type Language = 'en' | 'vi';

interface Props {
  language?: Language;
  t?: (key: string) => string;
  onNavigateBack?: () => void;
}

type FAQItem = {
  id: string;
  questionKey: string;
  answerKey: string;
};

const FAQ_ITEMS: FAQItem[] = [
  {
    id: 'flagged',
    questionKey: 'guided_ask.q_flagged',
    answerKey: 'guided_ask.a_flagged',
  },
  {
    id: 'why_flagged',
    questionKey: 'guided_ask.q_why_flagged',
    answerKey: 'guided_ask.a_why_flagged',
  },
  {
    id: 'what_next',
    questionKey: 'guided_ask.q_what_next',
    answerKey: 'guided_ask.a_what_next',
  },
  {
    id: 'not_assessed',
    questionKey: 'guided_ask.q_not_assessed',
    answerKey: 'guided_ask.a_not_assessed',
  },
  {
    id: 'what_test',
    questionKey: 'guided_ask.q_what_test',
    answerKey: 'guided_ask.a_what_test',
  },
];

const COPY_BY_LANGUAGE: Record<Language, Record<string, string>> = {
  en: {
    'guided_ask.title': 'Guided Questions',
    'guided_ask.wellness_boundary':
      'Wellness-support only. No diagnosis, treatment, or medication advice.',
    'guided_ask.intro':
      'Choose one of the safe questions below. Answers stay tied to the structured summary.',
    'guided_ask.q_flagged': 'What was flagged?',
    'guided_ask.a_flagged':
      'Flagged items are outside the supported range and stay tied to a value, label, and plain-language note.',
    'guided_ask.q_why_flagged': 'Why was it flagged?',
    'guided_ask.a_why_flagged':
      'Each result stays linked to the threshold source used for the review.',
    'guided_ask.q_what_next': 'What should I do next?',
    'guided_ask.a_what_next':
      'Follow the timing and next-step guidance shown on the patient summary.',
    'guided_ask.q_not_assessed': 'What was not assessed?',
    'guided_ask.a_not_assessed':
      'Anything unsupported stays visible in the summary instead of being hidden.',
    'guided_ask.q_what_test': 'What does this test measure?',
    'guided_ask.a_what_test':
      'It measures the analyte named on the card. Use the original report or a clinician for deeper interpretation.',
    'guided_ask.blocked_title': 'Out of scope',
    'guided_ask.blocked_text':
      'Diagnosis, treatment choice, medication changes, and symptom triage stay blocked here.',
    'guided_ask.back': 'Back to patient summary',
    'guided_ask.coach_label': 'Elfie Coach',
    'guided_ask.reply_label': 'Questions to explore',
  },
  vi: {
    'guided_ask.title': 'Câu Hỏi Hướng Dẫn',
    'guided_ask.wellness_boundary':
      'Chỉ hỗ trợ sức khỏe tổng quát. Không chẩn đoán, điều trị hay đề nghị đổi thuốc.',
    'guided_ask.intro':
      'Hãy chọn một câu hỏi an toàn bên dưới. Câu trả lời luôn bám vào bản tóm tắt có cấu trúc.',
    'guided_ask.q_flagged': 'Mục nào bị đánh dấu?',
    'guided_ask.a_flagged':
      'Các mục bị đánh dấu nằm ngoài khoảng được hỗ trợ và luôn đi cùng giá trị, nhãn, và ghi chú ngắn.',
    'guided_ask.q_why_flagged': 'Vì sao bị đánh dấu?',
    'guided_ask.a_why_flagged':
      'Mỗi kết quả luôn gắn với nguồn ngưỡng được dùng để xem xét.',
    'guided_ask.q_what_next': 'Tôi nên làm gì tiếp theo?',
    'guided_ask.a_what_next':
      'Hãy làm theo thời điểm và bước tiếp theo hiển thị trong bản tóm tắt bệnh nhân.',
    'guided_ask.q_not_assessed': 'Những gì chưa được đánh giá?',
    'guided_ask.a_not_assessed':
      'Mục không được hỗ trợ vẫn hiển thị trong tóm tắt thay vì bị ẩn.',
    'guided_ask.q_what_test': 'Xét nghiệm này đo gì?',
    'guided_ask.a_what_test':
      'Nó đo chất phân tích được ghi trên thẻ. Hãy xem báo cáo gốc hoặc hỏi bác sĩ để hiểu sâu hơn.',
    'guided_ask.blocked_title': 'Ngoài phạm vi',
    'guided_ask.blocked_text':
      'Không chẩn đoán, không đổi thuốc, không phân loại triệu chứng.',
    'guided_ask.back': 'Quay lại bản tóm tắt',
    'guided_ask.coach_label': 'Elfie Coach',
    'guided_ask.reply_label': 'Câu hỏi để xem thêm',
  },
};

export default function GuidedAsk({
  language = 'en',
  t,
  onNavigateBack,
}: Props) {
  const dictionary = COPY_BY_LANGUAGE[language];
  const [selectedId, setSelectedId] = useState<string>(FAQ_ITEMS[0].id);

  const resolveCopy = (key: string) => {
    const translated = t?.(key);
    if (translated && translated !== key) {
      return translated;
    }

    return dictionary[key] ?? COPY_BY_LANGUAGE.en[key] ?? key;
  };

  const selectedItem = useMemo(
    () => FAQ_ITEMS.find((item) => item.id === selectedId) ?? FAQ_ITEMS[0],
    [selectedId],
  );

  return (
    <PageChrome
      compact
      title={resolveCopy('guided_ask.title')}
      subtitle="Choose one safe question."
      contentMaxWidth={980}
    >
      <SurfaceCard
        style={{
          marginTop: '0.75rem',
          padding: '1.05rem',
          backgroundColor: STITCH_COLORS.surfaceLow,
          boxShadow: 'none',
        }}
      >
        <p
          style={{
            margin: '0 0 0.2rem',
            fontSize: '0.78rem',
            fontWeight: 800,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: STITCH_COLORS.textMuted,
          }}
        >
          {resolveCopy('guided_ask.coach_label')}
        </p>
        <p
          style={{
            margin: 0,
            fontSize: '0.94rem',
            lineHeight: 1.6,
            color: STITCH_COLORS.textSecondary,
          }}
        >
          {resolveCopy('guided_ask.intro')}
        </p>
      </SurfaceCard>

      <div className="stitch-faq-layout stitch-enter" style={{ marginTop: '1rem' }}>
        <SurfaceCard style={{ padding: '1.05rem' }}>
          <p
            style={{
              margin: '0 0 0.55rem',
              fontSize: '0.76rem',
              fontWeight: 800,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: STITCH_COLORS.textMuted,
            }}
          >
            {resolveCopy('guided_ask.reply_label')}
          </p>
          <div className="stitch-question-list">
            {FAQ_ITEMS.map((item) => {
              const isSelected = item.id === selectedItem.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelectedId(item.id)}
                  style={{
                    border: `1.5px solid ${
                      isSelected
                        ? 'rgba(255, 21, 112, 0.22)'
                        : STITCH_COLORS.borderGhost
                    }`,
                    borderRadius: STITCH_RADIUS.md,
                    padding: '0.88rem 0.95rem',
                    backgroundColor: isSelected
                      ? 'rgba(255, 21, 112, 0.08)'
                      : STITCH_COLORS.surfaceWhite,
                    color: isSelected
                      ? STITCH_COLORS.pink
                      : STITCH_COLORS.textHeading,
                    fontSize: '0.9rem',
                    fontWeight: 700,
                    lineHeight: 1.45,
                    textAlign: 'left',
                    cursor: 'pointer',
                    minHeight: 48,
                  }}
                >
                  {resolveCopy(item.questionKey)}
                </button>
              );
            })}
          </div>
        </SurfaceCard>

        <SurfaceCard style={{ padding: '1.25rem' }}>
          <div
            style={{
              display: 'flex',
              gap: '0.8rem',
              alignItems: 'flex-start',
            }}
          >
            <div
              aria-hidden="true"
              style={{
                width: 38,
                height: 38,
                borderRadius: '50%',
                backgroundColor: STITCH_COLORS.blueSoft,
                color: STITCH_COLORS.navy,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.96rem',
                flexShrink: 0,
              }}
            >
              💬
            </div>
            <div style={{ minWidth: 0 }}>
              <p
                style={{
                  margin: '0 0 0.3rem',
                  fontSize: '0.76rem',
                  fontWeight: 800,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: STITCH_COLORS.textMuted,
                }}
              >
                {resolveCopy(selectedItem.questionKey)}
              </p>
              <p
                style={{
                  margin: 0,
                  fontSize: '0.96rem',
                  lineHeight: 1.7,
                  color: STITCH_COLORS.textSecondary,
                }}
              >
                {resolveCopy(selectedItem.answerKey)}
              </p>
            </div>
          </div>

          <div className="stitch-divider" style={{ margin: '1rem 0' }} />

          <p
            style={{
              margin: '0 0 0.16rem',
              fontSize: '0.74rem',
              fontWeight: 800,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: STITCH_COLORS.warningText,
            }}
          >
            {resolveCopy('guided_ask.blocked_title')}
          </p>
          <p
            style={{
              margin: 0,
              fontSize: '0.86rem',
              lineHeight: 1.55,
              color: STITCH_COLORS.textSecondary,
            }}
          >
            {resolveCopy('guided_ask.blocked_text')} {resolveCopy('guided_ask.wellness_boundary')}
          </p>
        </SurfaceCard>
      </div>

      {onNavigateBack && (
        <SecondaryButton onClick={onNavigateBack} style={{ marginTop: '1rem' }}>
          {resolveCopy('guided_ask.back')}
        </SecondaryButton>
      )}
    </PageChrome>
  );
}
