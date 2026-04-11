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
        <SurfaceCard
          style={{
            padding: '1.25rem 1rem 1.1rem',
            marginTop: '0.9rem',
          }}
        >
          {selectedFile ? (
            <div>
              <div
                style={{
                  padding: '0.8rem 0.9rem',
                  borderRadius: STITCH_RADIUS.md,
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
                      margin: 0,
                      fontSize: '0.88rem',
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
                      fontSize: '0.78rem',
                      color: STITCH_COLORS.textSecondary,
                    }}
                  >
                    {isPdf
                      ? `PDF \u00B7 ${fileSizeLabel(selectedFile.size)} \u00B7 clearest results`
                      : isImage
                        ? `Image \u00B7 ${fileSizeLabel(selectedFile.size)} \u00B7 support may be partial`
                        : `${fileSizeLabel(selectedFile.size)}`}
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
                    marginTop: '0.75rem',
                    padding: '0.7rem 0.8rem',
                    borderRadius: STITCH_RADIUS.sm,
                    backgroundColor: STITCH_COLORS.errorBg,
                    color: STITCH_COLORS.errorText,
                    fontSize: '0.84rem',
                    lineHeight: 1.45,
                  }}
                >
                  {error}
                </div>
              )}

              <div style={{ marginTop: '1rem' }}>
                <PrimaryButton
                  type="submit"
                  disabled={!hasValidFile || uploading}
                >
                  {uploading ? 'Analyzing report\u2026' : 'Analyze Report'}
                </PrimaryButton>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              <p
                style={{
                  margin: '0 0 0.25rem',
                  fontSize: '0.92rem',
                  fontWeight: 600,
                  color: STITCH_COLORS.textHeading,
                  textAlign: 'center',
                }}
              >
                Choose a file to upload
              </p>

              <PrimaryButton
                type="button"
                onClick={() => pdfInputRef.current?.click()}
                disabled={uploading}
              >
                Upload PDF Report
              </PrimaryButton>

              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  margin: '0.18rem 0 0.2rem',
                }}
              >
                <div
                  style={{ flex: 1, height: 1, backgroundColor: STITCH_COLORS.borderGhost }}
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
                  style={{ flex: 1, height: 1, backgroundColor: STITCH_COLORS.borderGhost }}
                />
              </div>

              <button
                type="button"
                onClick={() => imageInputRef.current?.click()}
                disabled={uploading}
                style={{
                  border: 'none',
                  background: 'none',
                  color: STITCH_COLORS.blue,
                  fontSize: '0.86rem',
                  fontWeight: 700,
                  lineHeight: 1.4,
                  padding: '0.1rem 0',
                  cursor: uploading ? 'not-allowed' : 'pointer',
                  opacity: uploading ? 0.65 : 1,
                }}
              >
                Upload a photo instead (beta)
              </button>
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
            marginTop: '0.75rem',
            padding: '0.85rem 0.95rem',
            backgroundColor: STITCH_COLORS.surfaceLow,
            boxShadow: 'none',
          }}
        >
          <p
            style={{
              margin: '0 0 0.3rem',
              fontSize: '0.74rem',
              fontWeight: 800,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: STITCH_COLORS.textMuted,
            }}
          >
            For your safety
          </p>
          <p
            style={{
              margin: 0,
              fontSize: '0.86rem',
              lineHeight: 1.55,
              color: STITCH_COLORS.textSecondary,
            }}
          >
            This tool is for wellness support only, not a diagnosis or
            treatment plan. Photos and screenshots may not capture every result
            clearly, so we will show you exactly what we can and cannot review.
          </p>
        </SurfaceCard>

        <p
          style={{
            margin: '0.85rem 0 0',
            fontSize: '0.74rem',
            lineHeight: 1.5,
            color: STITCH_COLORS.textMuted,
            textAlign: 'center',
          }}
        >
          We check your results line by line before building a summary.
        </p>
      </form>
    </PageChrome>
  );
}
