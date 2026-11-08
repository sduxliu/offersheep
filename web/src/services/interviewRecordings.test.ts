import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get, post, del, createApiClient } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
  createApiClient: vi.fn(),
}));
vi.mock('./http', () => ({ createApiClient }));
createApiClient.mockReturnValue({ get, post, delete: del });

const {
  createReviewDraft,
  formatTranscriptForReview,
  listRecordings,
  mergeDraftField,
  startTranscription,
  uploadRecording,
} = await import('./interviewRecordings');

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  del.mockReset();
});

describe('mergeDraftField', () => {
  it('keeps existing content first and appends the labeled draft', () => {
    expect(mergeDraftField('已有记录', ' 草稿 ', 'AI 复盘')).toBe('已有记录\n\n【AI 复盘】\n草稿');
  });

  it('uses the draft alone when the field is empty and ignores an empty draft', () => {
    expect(mergeDraftField('  ', '草稿', 'x')).toBe('草稿');
    expect(mergeDraftField('原文', '  ', 'x')).toBe('原文');
  });
});

describe('createReviewDraft', () => {
  it('posts review context and unwraps the draft', async () => {
    post.mockResolvedValue({ data: { draft: { summary: 's', questions: 'q', self_reflection: 'r', difficulty_points: 'd' } } });
    await expect(createReviewDraft(9, { company: '星澜' })).resolves.toMatchObject({ summary: 's' });
    expect(post).toHaveBeenCalledWith('/interview-recordings/9/review-draft', { company: '星澜' }, { timeout: 180000 });
  });
});

describe('formatTranscriptForReview', () => {
  it('renders segments with mm:ss timestamps', () => {
    const output = formatTranscriptForReview('ignored', [
      { start: 0, end: 1, text: ' 请介绍一下项目 ' },
      { start: 65, end: 70, text: '再讲讲难点 ' },
    ]);
    expect(output).toBe('[00:00] 请介绍一下项目\n[01:05] 再讲讲难点');
  });

  it('falls back to plain text when there are no usable segments', () => {
    expect(formatTranscriptForReview(' 全文 ', [{ start: 0, end: 0, text: ' ' }])).toBe('全文');
  });
});

describe('interview recording service', () => {
  it('lists recordings by event id', async () => {
    get.mockResolvedValue({ data: [] });
    await expect(listRecordings(7)).resolves.toEqual([]);
    expect(get).toHaveBeenCalledWith('/interview-recordings', { params: { event_id: 7 } });
  });

  it('uploads the raw file with its filename and reports progress', async () => {
    post.mockImplementation((_url, _body, config) => {
      config.onUploadProgress({ loaded: 50, total: 100 });
      return Promise.resolve({ data: { id: 1, status: 'uploaded' } });
    });
    const file = new File(['abc'], '面试.m4a', { type: 'audio/mp4' });
    const progress: number[] = [];
    const result = await uploadRecording(3, file, (value) => progress.push(value));
    expect(result.id).toBe(1);
    expect(progress).toEqual([50]);
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe('/interview-events/3/recording');
    expect(body).toBe(file);
    expect(config.params).toEqual({ filename: '面试.m4a' });
    expect(config.headers['Content-Type']).toBe('audio/mp4');
  });

  it('starts transcription for a recording', async () => {
    post.mockResolvedValue({ data: { id: 5, status: 'transcribing' } });
    await expect(startTranscription(5)).resolves.toMatchObject({ status: 'transcribing' });
    expect(post).toHaveBeenCalledWith('/interview-recordings/5/transcribe');
  });
});
