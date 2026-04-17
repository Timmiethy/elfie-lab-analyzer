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
        const text = await response.text();
        throw new Error(text || `Upload failed with status ${response.status}`);
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
            padding: '7px 12px',
            borderRadius: STITCH_RADIUS.pill,
            backgroundColor: 'rgba(255,255,255,0.12)',
            border: '1px solid rgba(255,255,255,0.10)',
            fontSize: '0.74rem',
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
            marginTop: '1rem',
            padding: '1rem 1.1rem',
            borderRadius: STITCH_RADIUS.md,
            backgroundColor:
              notice.tone === 'error'
                ? STITCH_COLORS.errorBg
                : STITCH_COLORS.trustedBg,
            color:
              notice.tone === 'error'
                ? STITCH_COLORS.errorText
                : STITCH_COLORS.trustedText,
            fontSize: '0.92rem',
            lineHeight: 1.55,
          }}
        >
          {notice.text}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="stitch-enter" style={{ marginTop: '1rem', display: 'grid', gap: '0.9rem' }}>
          {/* ==================== SECTION 1: UPLOAD ACTION ==================== */}
          <SurfaceCard
            style={{
              padding: '1.5rem 1.25rem',
              background:
                'linear-gradient(180deg, rgba(255,255,255,0.99) 0%, rgba(255,246,248,0.94) 100%)',
            }}
          >
            {selectedFile ? (
              <div className="stitch-stack-tight">
                <div
                  style={{
                    padding: '1rem 1.05rem',
                    borderRadius: STITCH_RADIUS.lg,
                    backgroundColor: isPdf
                      ? STITCH_COLORS.trustedBg
                      : STITCH_COLORS.surfaceLow,
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: '0.85rem',
                    alignItems: 'flex-start',
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <p
                      style={{
                        margin: 0,
                        fontSize: '1rem',
                        fontWeight: 700,
                        color: STITCH_COLORS.textHeading,
                        wordBreak: 'break-word',
                      }}
                    >
                      {selectedFile.name}
                    </p>
                    <p
                      style={{
                        margin: '0.25rem 0 0',
                        fontSize: '0.84rem',
                        color: STITCH_COLORS.textSecondary,
                      }}
                    >
                      {isPdf
                        ? `PDF · ${fileSizeLabel(selectedFile.size)} · clearest coverage`
                        : isImage
                          ? `Image · ${fileSizeLabel(selectedFile.size)} · partial support`
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
                      fontSize: '0.88rem',
                      fontWeight: 700,
                      cursor: 'pointer',
                      padding: '0.25rem 0',
                      flexShrink: 0,
                      minHeight: 44,
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
                      padding: '0.8rem 0.9rem',
                      borderRadius: STITCH_RADIUS.md,
                      backgroundColor: STITCH_COLORS.errorBg,
                      color: STITCH_COLORS.errorText,
                      fontSize: '0.86rem',
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
                <p
                  style={{
                    margin: 0,
                    fontSize: '1.1rem',
                    fontWeight: 700,
                    lineHeight: 1.4,
                    color: STITCH_COLORS.textHeading,
                  }}
                >
                  Upload a PDF for the clearest summary.
                </p>
                <p
                  style={{
                    margin: '0.2rem 0 0.6rem',
                    fontSize: '0.86rem',
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  Photos work too (beta) · Max {MAX_SIZE_MB} MB
                </p>

                <div style={{ display: 'grid', gap: '0.5rem' }}>
                  <PrimaryButton
                    type="button"
                    onClick={() => pdfInputRef.current?.click()}
                    disabled={uploading}
                  >
                    Upload PDF
                  </PrimaryButton>
                  <SecondaryButton
                    type="button"
                    onClick={() => imageInputRef.current?.click()}
                    disabled={uploading}
                  >
                    Upload photo (beta)
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

          {/* ==================== SECTION 2: GUIDANCE ==================== */}
          <SurfaceCard
            style={{
              padding: '1rem 1.15rem',
              backgroundColor: STITCH_COLORS.surfaceLow,
              boxShadow: 'none',
            }}
          >
            <p
              style={{
                margin: 0,
                fontSize: '0.86rem',
                lineHeight: 1.55,
                color: STITCH_COLORS.textSecondary,
              }}
            >
              <strong style={{ color: STITCH_COLORS.textHeading }}>
                Before you upload:
              </strong>{' '}
              PDFs keep the clearest row structure · Image uploads may return a
              partial preview · Unsupported rows stay visible ·
              Wellness-support only, not a diagnosis.
            </p>
          </SurfaceCard>
        </div>
      </form>
    </PageChrome>
  );
}
