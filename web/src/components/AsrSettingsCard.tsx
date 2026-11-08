import { useEffect, useState } from 'react';
import { Alert, Button, Form, Input, Space, Switch, Typography, message } from 'antd';
import { t } from '@/i18n';
import {
  getAsrSettings,
  testAsrSettings,
  updateAsrSettings,
  type AsrSettingsView,
} from '@/services/interviewRecordings';

interface FormValues {
  base_url: string;
  model: string;
  api_key: string;
  enabled: boolean;
}

/** 面试录音的云端语音识别配置；密钥只写不读，界面仅显示掩码。 */
export default function AsrSettingsCard() {
  const [form] = Form.useForm<FormValues>();
  const [view, setView] = useState<AsrSettingsView | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    getAsrSettings()
      .then((value) => {
        setView(value);
        form.setFieldsValue({
          base_url: value.base_url,
          model: value.model,
          api_key: '',
          enabled: value.enabled,
        });
      })
      .catch(() => setView(null));
  }, [form]);

  async function handleSave(values: FormValues) {
    setSaving(true);
    try {
      const next = await updateAsrSettings({
        base_url: values.base_url,
        model: values.model,
        enabled: values.enabled,
        api_key: values.api_key || undefined,
      });
      setView(next);
      form.setFieldValue('api_key', '');
      message.success(t('语音识别配置已保存'));
    } catch (error) {
      const payload = (error as { response?: { data?: { error?: string } } })?.response?.data;
      message.error(payload?.error || t('保存失败，请重试'));
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testAsrSettings();
      setTestResult(result.ok
        ? { ok: true, text: t('连接成功（{ms} 毫秒）', { ms: result.latency_ms ?? 0 }) }
        : { ok: false, text: result.error || t('连接失败') });
    } catch {
      setTestResult({ ok: false, text: t('连接失败') });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div style={{ marginTop: 12 }}>
      <Typography.Text strong>{t('面试录音转写（云端语音识别）')}</Typography.Text>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: '4px 0 12px' }}>
        {t('使用 OpenAI 兼容的 /audio/transcriptions 接口，默认硅基流动 SenseVoiceSmall。密钥只保存在本机数据目录。')}
      </Typography.Paragraph>
      <Form form={form} layout="vertical" onFinish={handleSave} initialValues={{ enabled: false }}>
        <Form.Item name="enabled" label={t('启用转写')} valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="base_url" label={t('服务地址')} rules={[{ required: true, message: t('请输入服务地址') }]}>
          <Input placeholder="https://api.siliconflow.cn/v1" />
        </Form.Item>
        <Form.Item name="model" label={t('模型')} rules={[{ required: true, message: t('请输入模型名') }]}>
          <Input placeholder="FunAudioLLM/SenseVoiceSmall" />
        </Form.Item>
        <Form.Item
          name="api_key"
          label={t('API Key')}
          extra={view?.api_key_set
            ? t('已设置（{hint}），留空则保持不变', { hint: view.api_key_hint })
            : t('尚未设置')}
        >
          <Input.Password autoComplete="new-password" placeholder={t('粘贴新的 API Key')} />
        </Form.Item>
        <Space wrap>
          <Button type="primary" htmlType="submit" loading={saving}>{t('保存')}</Button>
          <Button onClick={() => void handleTest()} loading={testing}>{t('测试连接')}</Button>
        </Space>
      </Form>
      {testResult ? (
        <Alert
          style={{ marginTop: 12 }}
          type={testResult.ok ? 'success' : 'error'}
          showIcon
          message={testResult.text}
        />
      ) : null}
      {view && !view.ffmpeg_available ? (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
          {t('未检测到 ffmpeg：长录音将整文件提交，可能超出服务商单文件限制。安装 ffmpeg 后会自动按 10 分钟分片转写。')}
        </Typography.Paragraph>
      ) : null}
    </div>
  );
}
