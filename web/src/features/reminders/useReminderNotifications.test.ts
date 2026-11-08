import { describe, expect, it } from 'vitest';
import type { ScheduleEvent } from '@/types/event';
import { dueReminders, reminderKey, reminderText } from './useReminderNotifications';

const NOW = Date.parse('2026-11-20T10:00:00+08:00');

function event(overrides: Partial<ScheduleEvent>): ScheduleEvent {
  return {
    id: 1, application_id: 7, event_type: 'custom', subtype: '跟进一面结果', tags: [], round: 0,
    scheduled_at: '2026-11-20T11:00:00+08:00', duration_minutes: 30, location: '', notes: '',
    remind_at: '2026-11-20T09:30:00+08:00', status: 'todo', company_name: '星澜智能',
    position_name: '测试开发', created_at: '2026-11-01T00:00:00+08:00', ...overrides,
  };
}

describe('dueReminders', () => {
  it('returns todo events whose reminder time has passed recently', () => {
    expect(dueReminders([event({})], NOW, new Set()).map((item) => item.id)).toEqual([1]);
  });

  it('skips future, completed, already-notified and long-overdue reminders', () => {
    const items = [
      event({ id: 2, remind_at: '2026-11-20T10:30:00+08:00' }),
      event({ id: 3, status: 'done' }),
      event({ id: 4 }),
      event({ id: 5, remind_at: '2026-11-19T08:00:00+08:00' }),
      event({ id: 6, remind_at: null }),
    ];
    const notified = new Set([reminderKey(items[2])]);
    expect(dueReminders(items, NOW, notified)).toEqual([]);
  });
});

describe('reminderText', () => {
  it('names the todo, the company and the scheduled time', () => {
    const text = reminderText(event({}));
    expect(text.title).toContain('跟进一面结果');
    expect(text.body).toContain('星澜智能 · 测试开发');
  });
});
