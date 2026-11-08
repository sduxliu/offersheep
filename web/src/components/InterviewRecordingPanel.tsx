import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Progress, Space, Tag, Typography } from 'antd';
import { ReloadOutlined, RobotOutlined, UploadOutlined } from '@ant-design/icons';
import { t } from '@/i18n';
import {
  createReviewDraft,
  deleteRecording,
  formatTranscriptForReview,
  getRecordingCapability,
  getRecording,
  listRecordings,
  startTranscription,
  uploadRecording,
  type RecordingReviewDraft,
} from '@/services/interviewRecordings';
import { createEvent } from '@/services/events';
import type { InterviewRecording } from '@/types/interviewRecording';

const POLL_MS = 2500;

interface Props {
  applicationEventId?: number | null;
  applicationId?: number | null;
  onFillTranscript: (text: string) => void;
  onFillDraft?: (draft: RecordingReviewDraft) => void;
  getReviewContext?: () => { company?: string; position?: string; round?: string };
}

export default function InterviewRecordingPanel({
  applicationEventId,
  applicationId,
  onFillTranscript,
  onFillDraft,
  getReviewContext,
}: Props) {
  const [recordings, setRecordings] = useState<InterviewRecording[]>([]);
  const [capability, setCapability] = useState<{ enabled: boolean; reason: string } | null>(null);
  const [uploadingPercent, setUploadingPercent] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [followUpSaved, setFollowUpSaved] = useState(false);
  const [draftingId, setDraftingId] = useState<number | null>(null);
  const [draftNotice, setDraftNotice] = useState('');
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const hasActiveJob = recordings.some((item) => item.status === 'transcribing');

  const refreshOne = useCallback(async (id: number) => {
    try {
      const fresh = await getRecording(id);
      setRecordings((prev) => prev.map((item) => (item.id === id ? fresh : item)));
    } catch {
      /* 单条刷新失败留给下一轮轮询 */
    }
  }, []);

  useEffect(() => {
    if (!applicationEventId) {
      setRecordings([]);
      return;
    }
    let cancelled = false;
    listRecordings(applicationEventId)
      .then((items) => {
        if (!cancelled) setRecordings(items);
      })
      .catch(() => setError(t('录音列表读取失败')));
    getRecordingCapability()
      .then((value) => setCapability(value))
      .catch(() => setCapability({ enabled: false, reason: '' }));
    return () => {
      cancelled = true;
    };
  }, [applicationEventId]);

  useEffect(() => {
    if (!hasActiveJob) {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
      return;
    }
    pollTimer.current = setInterval(() => {
      recordings
        .filter((item) => item.status === 'transcribing')
        .forEach((item) => {
          void refreshOne(item.id);
        });
    }, POLL_MS);
    return () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [hasActiveJob, recordings, refreshOne]);

  async function handleUpload(file: File) {
    if (!applicationEventId) return;
    setError('');
    setUploadingPercent(0);
    try {
      const created = await uploadRecording(applicationEventId, file, setUploadingPercent);
      setRecordings((prev) => [created, ...prev]);
      if (capability?.enabled) {
        const started = await startTranscription(created.id);
        setRecordings((prev) => prev.map((item) => (item.id === created.id ? started : item)));
      }
    } catch (err) {
      const payload = (err as { response?: { data?: { error?: string } } })?.response?.data;
      setError(payload?.error || t('上传失败，请重试'));
    } finally {
      setUploadingPercent(null);
    }
  }

  async function handleTranscribe(id: number) {
    setError('');
    try {
      const started = await startTranscription(id);
      setRecordings((prev) => prev.map((item) => (item.id === id ? started : item)));
    } catch (err) {
      const payload = (err as { response?: { data?: { error?: string } } })?.response?.data;
      setError(payload?.error || t('转写启动失败'));
    }
  }

  async function handleDelete(id: number) {
    setError('');
    try {
      await deleteRecording(id);
      setRecordings((prev) => prev.filter((item) => item.id !== id));
    } catch {
      setError(t('删除失败，请重试'));
    }
  }

  async function handleDraft(id: number) {
    if (!onFillDraft) return;
    setError('');
    setDraftNotice('');
    setDraftingId(id);
    try {
      const draft = await createReviewDraft(id, getReviewContext ? getReviewContext() : {});
      onFillDraft(draft);
      setDraftNotice(t('AI 复盘草稿已填入下方表单，请核对修改后点击「保存复盘」。'));
    } catch (err) {
      const payload = (err as { response?: { data?: { error?: string } } })?.response?.data;
      setError(payload?.error || t('AI 复盘生成失败，请重试'));
    } finally {
      setDraftingId(null);
    }
  }

  async function handleFollowUp() {
    if (!applicationId) return;
    const due = new Date(Date.now() + 3 * 24 * 3600 * 1000);
    try {
      await createEvent({
        application_id: applicationId,
        event_type: 'custom',
        subtype: t('跟进面试结果'),
        scheduled_at: due.toISOString(),
        duration_minutes: 0,
        notes: t('面试已结束：确认结果、更新投递状态。'),
      });
      setFollowUpSaved(true);
    } catch {
      setError(t('提醒创建失败，请重试'));
    }
  }

  return (
    <div style={{ margin: '4px 0 18px', padding: 12, border: '1px solid #f0f0f0', borderRadius: 8 }}>
      <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Text strong>{t('面试录音')}</Typography.Text>
        <Space wrap>
          {applicationEventId ? (
            <>
              <label>
                <input
                  type="file"
                  accept=".mp3,.m4a,.aac,.wav,.webm,audio/*"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = '';
                    if (file) void handleUpload(file);
                  }}
                />
                <Button size="small" icon={<UploadOutlined />} loading={uploadingPercent !== null}>
                  {t('上传录音')}
                </Button>
              </label>
              <Button size="small" icon={<ReloadOutlined />} onClick={() => {
                if (applicationEventId) {
                  void listRecordings(applicationEventId).then(setRecordings);
                }
              }}>
                {t('刷新')}
              </Button>
            </>
          ) : (
            <Typography.Text type="secondary">{t('绑定面试事件后可上传录音')}</Typography.Text>
          )}
        </Space>
      </Space>

      {error ? <Alert style={{ marginTop: 8 }} type="error" showIcon message={error} /> : null}
      {draftNotice ? <Alert style={{ marginTop: 8 }} type="success" showIcon message={draftNotice} /> : null}
      {capability && !capability.enabled ? (
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
          {t('语音识别服务未配置：可先上传录音，在 设置 → 语音 中配置后再点「开始转写」。')}
        </Typography.Text>
      ) : null}
      {uploadingPercent !== null ? (
        <Progress percent={uploadingPercent} size="small" style={{ marginTop: 8 }} />
      ) : null}

      {recordings.map((item) => (
        <div key={item.id} style={{ marginTop: 10, padding: 8, background: '#fafafa', borderRadius: 6 }}>
          <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space wrap>
              <Typography.Text style={{ maxWidth: 260 }} ellipsis>{item.filename}</Typography.Text>
              <Tag color={
                item.status === 'completed' ? 'green'
                  : item.status === 'transcribing' ? 'blue'
                    : item.status === 'failed' ? 'red' : 'default'
              }>
                {item.status === 'completed' ? t('转写完成')
                  : item.status === 'transcribing' ? t('转写中') + (item.chunk_count > 0 ? ` ${item.chunks_done}/${item.chunk_count}` : '')
                    : item.status === 'failed' ? t('转写失败') : t('已上传')}
              </Tag>
            </Space>
            <Space wrap>
              {item.status === 'uploaded' || item.status === 'failed' ? (
                <Button size="small" type="link" onClick={() => void handleTranscribe(item.id)}>
                  {t('开始转写')}
                </Button>
              ) : null}
              {item.status === 'completed' ? (
                <>
                  {onFillDraft ? (
                    <Button
                      size="small"
                      type="primary"
                      icon={<RobotOutlined />}
                      loading={draftingId === item.id}
                      onClick={() => void handleDraft(item.id)}
                    >
                      {t('AI 生成复盘')}
                    </Button>
                  ) : null}
                  <Button size="small" type="link" onClick={() => onFillTranscript(
                    formatTranscriptForReview(item.transcript_text, item.transcript_segments)
                  )}>
                    {t('填入原文')}
                  </Button>
                  {!followUpSaved && applicationId ? (
                    <Button size="small" type="link" onClick={() => void handleFollowUp()}>
                      {t('3天后提醒跟进')}
                    </Button>
                  ) : null}
                </>
              ) : null}
              <Button size="small" type="link" danger onClick={() => void handleDelete(item.id)}>
                {t('删除')}
              </Button>
            </Space>
          </Space>
          {item.status === 'transcribing' && item.chunk_count > 0 ? (
            <Progress
              size="small"
              style={{ marginTop: 4 }}
              percent={Math.round((item.chunks_done / item.chunk_count) * 100)}
            />
          ) : null}
          {item.status === 'failed' && item.error_code ? (
            <Typography.Text type="danger" style={{ fontSize: 12 }}>
              {item.error_code}
            </Typography.Text>
          ) : null}
          {item.status === 'completed' ? (
            <Typography.Paragraph
              style={{ marginTop: 6, marginBottom: 0, fontSize: 12, whiteSpace: 'pre-wrap' }}
              ellipsis={{ rows: 4, expandable: true, symbol: t('展开全文') }}
            >
              {formatTranscriptForReview(item.transcript_text, item.transcript_segments)}
            </Typography.Paragraph>
          ) : null}
        </div>
      ))}
    </div>
  );
}
