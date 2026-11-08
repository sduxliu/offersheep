import { useState } from 'react';
import { Input, Modal, Select, message } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { t } from '@/i18n';
import { liveText } from '@/i18n/liveText';
import { updateApplication } from '@/services/applications';
import { STATUS_LABELS, type Application, type ApplicationStatus } from '@/types/application';
import { buildApplicationStatusPayload, requiresClosedReason } from './KanbanBoard/applicationLifecycle';

const ORDER: ApplicationStatus[] = ['pending', 'applied', 'written_test', 'interview', 'offer', 'closed'];

/** 详情页的投递状态快捷切换：与看板拖拽共用状态规则，结束投递需填写原因。 */
export default function ApplicationStatusSwitcher({ application }: { application: Application }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<ApplicationStatus | null>(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  async function save(next: ApplicationStatus) {
    if (requiresClosedReason(application.status, next) && !reason.trim()) {
      message.error(liveText(() => t('请填写关闭原因')));
      return;
    }
    setSaving(true);
    try {
      await updateApplication(application.id, buildApplicationStatusPayload(application, next, reason));
      await queryClient.invalidateQueries({ queryKey: ['applications'] });
      await queryClient.invalidateQueries({ queryKey: ['events'] });
      message.success(liveText(() => t('已移至「{value1}」', { value1: STATUS_LABELS[next] })));
      setPending(null);
      setReason('');
    } catch {
      message.error(liveText(() => t('状态更新失败，请重试')));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Select<ApplicationStatus>
        size="small"
        aria-label={t('投递状态')}
        value={application.status}
        style={{ minWidth: 120 }}
        options={ORDER.map((status) => ({ value: status, label: STATUS_LABELS[status] }))}
        onChange={(next) => {
          if (next === application.status) return;
          if (requiresClosedReason(application.status, next)) setPending(next);
          else void save(next);
        }}
      />
      <Modal
        title={t('确认更新投递状态')}
        open={pending !== null}
        okText={t('确认更新')}
        cancelText={t('取消')}
        confirmLoading={saving}
        onOk={() => { if (pending) void save(pending); }}
        onCancel={() => { setPending(null); setReason(''); }}
      >
        <Input.TextArea
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder={t('填写关闭原因，例如：岗位关闭、主动放弃、已接受其他 offer')}
        />
      </Modal>
    </>
  );
}
