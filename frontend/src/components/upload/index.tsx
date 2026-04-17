import {
  useCallback,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from 'react';
import { uploadFile } from '../../services/api';
import type { LaneType, UploadResponse } from '../../types';
import {
  PageChrome,
  PrimaryButton,
  SecondaryButton,
  SurfaceCard,
} from '../common';
import {
  STITCH_COLORS,
  STITCH_RADIUS,
} from '../common/system';

const PDF_TYPE = 'application/pdf';
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/tiff', 'image/webp'];
const ALL_TYPES = [PDF_TYPE, ...IMAGE_TYPES];
const MAX_SIZE_MB = 25;

function validateFile(file: File): string | null {
  if (!ALL_TYPES.includes(file.type)) {
    return 'Please upload a PDF or an image (PNG, JPG, TIFF, WebP).';
  }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) {
    return `File is too large. Maximum size is ${MAX_SIZE_MB} MB.`;
  }
  return null;
}

function fileSizeLabel(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

async function parseUploadError(response: Response): Promise<string> {
  const fallback = `Upload failed with status ${response.status}`;

  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload.detail === 'processing_failed') {
      return 'We could not parse supported rows from this file. Please try a clearer PDF export or a different report.';
    }
    if (typeof payload.detail === 'string' && payload.detail.length > 0) {
      return payload.detail;
    }
  } catch {
    // Fall back to text payload when response is not JSON.
  }

  const text = await response.text();
  return text || fallback;
}

interface Props {
  onJobStarted: (jobId: string, laneType: LaneType) => void;
  notice?: { tone: 'success' | 'error'; text: string } | null;
}

export default function Upload({ onJobStarted, notice = null }: Props) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const pdfInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const clearFile = useCallback(() => {
    setSelectedFile(null);
    setError(null);
    if (pdfInputRef.current) {
      pdfInputRef.current.value = '';
    }
    if (imageInputRef.current) {
      imageInputRef.current.value = '';
    }
  }, []);

  const assignFile = useCallback((file: File | null) => {
    setSelectedFile(file);
    if (!file) {
      setError(null);
      return;
    }

    const validation = validateFile(file);
    setError(validation);
  }, []);

  const handlePdfChange = (event: ChangeEvent<HTMLInputElement>) => {
    assignFile(event.target.files?.[0] ?? null);
  };

  const handleImageChange = (event: ChangeEvent<HTMLInputElement>) => {
    assignFile(event.target.files?.[0] ?? null);
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();

    if (!selectedFile) {
      setError('Please select a file first.');
      return;
    }

    const validation = validateFile(selectedFile);
    if (validation) {
      setError(validation);
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const response = await uploadFile(selectedFile);
      if (!response.ok) {
        throw new Error(await parseUploadError(response));
      }

      const data: UploadResponse = await response.json();
      onJobStarted(data.job_id, data.lane_type);
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : 'Upload failed. Please try again.',
      );
    } finally {
      setUploading(false);
    }
  };

  const isPdf = selectedFile?.type === PDF_TYPE;
  const isImage = selectedFile ? selectedFile.type.startsWith('image/') : false;
  const hasValidFile = Boolean(selectedFile && !error);

  return (
    <PageChrome
      compact
      title="Upload Lab Report"
      subtitle="PDFs give the clearest summary."
      rightSlot={
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '6px 10px',
            borderRadius: STITCH_RADIUS.pill,
            backgroundColor: 'rgba(255,255,255,0.12)',
            border: '1px solid rgba(255,255,255,0.10)',
            fontSize: '0.72rem',
            fontWeight: 700,
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              backgroundColor: '#6BFE9C',
              display: 'inline-block',
            }}
          />
          Recommended
        </div>
      }
      contentMaxWidth={1040}
    >
      {notice && (
        <div
          role="status"
          style={{
            marginTop: '0.8rem',
            padding: '0.95rem 1rem',
            borderRadius: STITCH_RADIUS.md,
            backgroundColor:
              notice.tone === 'error'
                ? STITCH_COLORS.errorBg
                : STITCH_COLORS.trustedBg,
            color:
              notice.tone === 'error'
                ? STITCH_COLORS.errorText
                : STITCH_COLORS.trustedText,
            fontSize: '0.88rem',
            lineHeight: 1.5,
          }}
        >
          {notice.text}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="stitch-upload-layout stitch-enter" style={{ marginTop: '0.9rem' }}>
          <SurfaceCard
            style={{
              padding: '1.25rem 1rem 1.1rem',
              background:
                'linear-gradient(180deg, rgba(255,255,255,0.99) 0%, rgba(255,246,248,0.94) 100%)',
            }}
          >
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '0.5rem',
                marginBottom: '0.9rem',
              }}
            >
              {['PDF preferred', 'Images supported', `Max ${MAX_SIZE_MB} MB`].map(
                (label) => (
                  <span
                    key={label}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      padding: '0.38rem 0.72rem',
                      borderRadius: STITCH_RADIUS.pill,
                      backgroundColor: STITCH_COLORS.surfaceWhite,
                      border: `1px solid ${STITCH_COLORS.borderGhost}`,
                      fontSize: '0.74rem',
                      fontWeight: 700,
                      color: STITCH_COLORS.textSecondary,
                    }}
                  >
                    {label}
                  </span>
                ),
              )}
            </div>

            {selectedFile ? (
              <div className="stitch-stack-tight">
                <div
                  style={{
                    padding: '0.9rem 0.95rem',
                    borderRadius: STITCH_RADIUS.lg,
                    backgroundColor: isPdf
                      ? STITCH_COLORS.trustedBg
                      : STITCH_COLORS.surfaceLow,
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: '0.75rem',
                    alignItems: 'flex-start',
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <p
                      style={{
                        margin: '0 0 0.18rem',
                        fontSize: '0.72rem',
                        fontWeight: 800,
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        color: STITCH_COLORS.textMuted,
                      }}
                    >
                      Selected file
                    </p>
                    <p
                      style={{
                        margin: 0,
                        fontSize: '0.94rem',
                        fontWeight: 700,
                        color: STITCH_COLORS.textHeading,
                        wordBreak: 'break-word',
                      }}
                    >
                      {selectedFile.name}
                    </p>
                    <p
                      style={{
                        margin: '0.28rem 0 0',
                        fontSize: '0.8rem',
                        lineHeight: 1.5,
                        color: STITCH_COLORS.textSecondary,
                      }}
                    >
                      {isPdf
                        ? `PDF · ${fileSizeLabel(selectedFile.size)} · clearest support coverage`
                        : isImage
                          ? `Image · ${fileSizeLabel(selectedFile.size)} · support may be partial`
                          : fileSizeLabel(selectedFile.size)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={clearFile}
                    style={{
                      border: 'none',
                      background: 'none',
                      color: STITCH_COLORS.textSecondary,
                      fontSize: '0.82rem',
                      fontWeight: 700,
                      cursor: 'pointer',
                      padding: 0,
                      flexShrink: 0,
                    }}
                    aria-label="Remove selected file"
                  >
                    Remove
                  </button>
                </div>

                {error && (
                  <div
                    role="alert"
                    style={{
                      padding: '0.75rem 0.85rem',
                      borderRadius: STITCH_RADIUS.md,
                      backgroundColor: STITCH_COLORS.errorBg,
                      color: STITCH_COLORS.errorText,
                      fontSize: '0.84rem',
                      lineHeight: 1.5,
                    }}
                  >
                    {error}
                  </div>
                )}

                <PrimaryButton
                  type="submit"
                  disabled={!hasValidFile || uploading}
                >
                  {uploading ? 'Analyzing report…' : 'Analyze report'}
                </PrimaryButton>
              </div>
            ) : (
              <div className="stitch-stack-tight">
                <div>
                  <p
                    style={{
                      margin: '0 0 0.16rem',
                      fontSize: '0.76rem',
                      fontWeight: 800,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                      color: STITCH_COLORS.textMuted,
                    }}
                  >
                    Start with the clearest file
                  </p>
                  <p
                    style={{
                      margin: 0,
                      fontSize: '1.1rem',
                      fontWeight: 700,
                      lineHeight: 1.4,
                      color: STITCH_COLORS.textHeading,
                    }}
                  >
                    Upload a PDF report first, or use a photo when that is all
                    you have.
                  </p>
                </div>

                <div
                  style={{
                    padding: '1rem',
                    borderRadius: STITCH_RADIUS.lg,
                    backgroundColor: STITCH_COLORS.surfaceWhite,
                    border: `1px solid ${STITCH_COLORS.borderGhost}`,
                  }}
                >
                  <PrimaryButton
                    type="button"
                    onClick={() => pdfInputRef.current?.click()}
                    disabled={uploading}
                  >
                    Upload PDF report
                  </PrimaryButton>

                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      margin: '0.8rem 0',
                    }}
                  >
                    <div
                      style={{
                        flex: 1,
                        height: 1,
                        backgroundColor: STITCH_COLORS.borderGhost,
                      }}
                    />
                    <span
                      style={{
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.06em',
                        color: STITCH_COLORS.textMuted,
                      }}
                    >
                      or
                    </span>
                    <div
                      style={{
                        flex: 1,
                        height: 1,
                        backgroundColor: STITCH_COLORS.borderGhost,
                      }}
                    />
                  </div>

                  <SecondaryButton
                    type="button"
                    onClick={() => imageInputRef.current?.click()}
                    disabled={uploading}
                  >
                    Upload a photo instead (beta)
                  </SecondaryButton>
                </div>
              </div>
            )}

            <input
              ref={pdfInputRef}
              type="file"
              accept=".pdf,application/pdf"
              onChange={handlePdfChange}
              style={{ display: 'none' }}
            />
            <input
              ref={imageInputRef}
              type="file"
              accept=".png,.jpg,.jpeg,.tiff,.webp,image/png,image/jpeg,image/tiff,image/webp"
              onChange={handleImageChange}
              style={{ display: 'none' }}
            />
          </SurfaceCard>

          <SurfaceCard
            style={{
              padding: '1rem',
              backgroundColor: STITCH_COLORS.surfaceLow,
              boxShadow: 'none',
            }}
          >
            <p
              style={{
                margin: '0 0 0.22rem',
                fontSize: '0.74rem',
                fontWeight: 800,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: STITCH_COLORS.textMuted,
              }}
            >
              Before you upload
            </p>
            <p
              style={{
                margin: 0,
                fontSize: '0.92rem',
                fontWeight: 700,
                lineHeight: 1.45,
                color: STITCH_COLORS.textHeading,
              }}
            >
              Start with a PDF when possible. Use a photo only when you do not
              have the original report.
            </p>

            <div className="stitch-divider" style={{ margin: '0.85rem 0' }} />

            <ul className="stitch-helper-list">
              <li>PDFs usually keep the clearest row structure.</li>
              <li>Image uploads may return a partial preview only.</li>
              <li>Unsupported rows stay visible instead of being hidden.</li>
            </ul>

            <p
              style={{
                margin: '0.85rem 0 0',
                fontSize: '0.82rem',
                lineHeight: 1.55,
                color: STITCH_COLORS.textSecondary,
              }}
            >
              Wellness-support only. No diagnosis or treatment advice.
            </p>
          </SurfaceCard>
        </div>
      </form>
    </PageChrome>
  );
}