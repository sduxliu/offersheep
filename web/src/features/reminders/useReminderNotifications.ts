import { useEffect } from 'react';
import { t } from '@/i18n';
import { listEvents } from '@/services/events';
import { EVENT_TYPE_LABELS, type ScheduleEvent } from '@/types/event';

const STORAGE_KEY = 'offersheep:notified-reminders';
const POLL_MS = 60_000;
/** 只补发 12 小时内错过的提醒，避免打开应用时一次弹出大量旧提醒。 */
const CATCH_UP_MS = 12 * 3600_000;

export function notificationsSupported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window;
}

export async function requestReminderNotifications(): Promise<NotificationPermission | 'unsupported'> {
  if (!notificationsSupported()) return 'unsupported';
  return Notification.requestPermission();
}

function readNotified(): Set<string> {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    return new Set(Array.isArray(raw) ? raw.map(String) : []);
  } catch {
    return new Set();
  }
}

function writeNotified(keys: Set<string>): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...keys].slice(-200)));
}

export function reminderKey(event: ScheduleEvent): string {
  return `${event.id}@${event.remind_at ?? ''}`;
}

/** 选出已到提醒时间、尚未通知过的未完成待办（纯函数）。 */
export function dueReminders(events: ScheduleEvent[], now: number, notified: Set<string>): ScheduleEvent[] {
  return events.filter((event) => {
    if (event.status !== 'todo' || !event.remind_at) return false;
    const at = Date.parse(event.remind_at);
    if (Number.isNaN(at) || at > now || now - at > CATCH_UP_MS) return false;
    return !notified.has(reminderKey(event));
  });
}

export function reminderText(event: ScheduleEvent): { title: string; body: string } {
  const what = event.subtype || EVENT_TYPE_LABELS[event.event_type];
  const who = [event.company_name, event.position_name].filter(Boolean).join(' · ');
  const when = new Date(event.scheduled_at).toLocaleString();
  return { title: t('OfferSheep 提醒：{what}', { what }), body: [who, when].filter(Boolean).join('\n') };
}

/** 应用打开期间每分钟检查一次到点的待办，用系统通知提醒（需用户授权）。 */
export function useReminderNotifications(): void {
  useEffect(() => {
    if (!notificationsSupported()) return;
    let stopped = false;
    const check = async () => {
      if (Notification.permission !== 'granted') return;
      try {
        const events = await listEvents();
        if (stopped) return;
        const notified = readNotified();
        for (const event of dueReminders(events, Date.now(), notified)) {
          const { title, body } = reminderText(event);
          new Notification(title, { body, tag: `offersheep-event-${event.id}` });
          notified.add(reminderKey(event));
        }
        writeNotified(notified);
      } catch {
        /* 读取失败时等待下一轮 */
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, []);
}
