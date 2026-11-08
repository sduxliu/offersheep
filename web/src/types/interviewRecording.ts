export interface InterviewRecording {
  id: number;
  application_id: number | null;
  application_event_id: number | null;
  note_id: number | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  duration_seconds: number | null;
  status: 'uploaded' | 'transcribing' | 'completed' | 'failed';
  error_code: string;
  transcript_text: string;
  transcript_segments: TranscriptSegment[];
  transcript_language: string;
  asr_provider: string;
  asr_model: string;
  chunk_count: number;
  chunks_done: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface InterviewRecordingCapability {
  enabled: boolean;
  reason: string;
  provider: string;
  model: string;
  ffmpeg_available: boolean;
  max_file_bytes: number;
}
