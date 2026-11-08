import type {
  InterviewRecording,
  InterviewRecordingCapability,
  TranscriptSegment,
} from '@/types/interviewRecording';
import { createApiClient } from './http';

const http = createApiClient({
  baseURL: '/api',
  timeout: 15000,
});

export async function getRecordingCapability(): Promise<InterviewRecordingCapability> {
  const { data } = await http.get<InterviewRecordingCapability>('/interview-recordings/capability');
  return data;
}

export async function listRecordings(eventId: number): Promise<InterviewRecording[]> {
  const { data } = await http.get<InterviewRecording[]>('/interview-recordings', {
    params: { event_id: eventId },
  });
  return data;
}

export async function getRecording(id: number): Promise<InterviewRecording> {
  const { data } = await http.get<InterviewRecording>(`/interview-recordings/${id}`);
  return data;
}

export async function uploadRecording(
  eventId: number,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<InterviewRecording> {
  const { data } = await http.post<InterviewRecording>(
    `/interview-events/${eventId}/recording`,
    file,
    {
      params: { filename: file.name },
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      timeout: 0,
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
    },
  );
  return data;
}

export async function startTranscription(id: number): Promise<InterviewRecording> {
  const { data } = await http.post<InterviewRecording>(`/interview-recordings/${id}/transcribe`);
  return data;
}

export async function deleteRecording(id: number): Promise<void> {
  await http.delete(`/interview-recordings/${id}`);
}

export interface RecordingReviewDraft {
  summary: string;
  questions: string;
  self_reflection: string;
  difficulty_points: string;
}

/** 转写稿 → AI 复盘草稿；只返回草稿，保存仍由用户在复盘表单确认。 */
export async function createReviewDraft(
  id: number,
  context: { company?: string; position?: string; round?: string },
): Promise<RecordingReviewDraft> {
  const { data } = await http.post<{ draft: RecordingReviewDraft }>(
    `/interview-recordings/${id}/review-draft`,
    context,
    { timeout: 180000 },
  );
  return data.draft;
}

export interface AsrSettingsView {
  provider: string;
  base_url: string;
  model: string;
  language: string;
  enabled: boolean;
  api_key_set: boolean;
  api_key_hint: string;
  ffmpeg_available: boolean;
}

export interface AsrSettingsUpdate {
  base_url?: string;
  model?: string;
  language?: string;
  enabled?: boolean;
  api_key?: string;
  clear_api_key?: boolean;
}

export async function getAsrSettings(): Promise<AsrSettingsView> {
  const { data } = await http.get<AsrSettingsView>('/settings/asr');
  return data;
}

export async function updateAsrSettings(update: AsrSettingsUpdate): Promise<AsrSettingsView> {
  const { data } = await http.put<AsrSettingsView>('/settings/asr', update);
  return data;
}

export async function testAsrSettings(): Promise<{ ok: boolean; error?: string; latency_ms?: number }> {
  const { data } = await http.post<{ ok: boolean; error?: string; latency_ms?: number }>(
    '/settings/asr/test',
    undefined,
    { timeout: 120000 },
  );
  return data;
}

/** 草稿字段与已有内容合并：已有内容保留在前，草稿追加在后。 */
export function mergeDraftField(existing: string, addition: string, label: string): string {
  const current = existing.trim();
  const next = addition.trim();
  if (!next) return current;
  if (!current) return next;
  return `${current}\n\n【${label}】\n${next}`;
}

function clock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const mm = String(Math.floor(total / 60)).padStart(2, '0');
  const ss = String(total % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

/** 把转写结果整理成可直接填入「面试问题」字段的带时间戳文本。 */
export function formatTranscriptForReview(
  text: string,
  segments: TranscriptSegment[],
): string {
  const usable = segments.filter((item) => item.text.trim());
  if (usable.length === 0) return text.trim();
  return usable.map((item) => `[${clock(item.start)}] ${item.text.trim()}`).join('\n');
}
