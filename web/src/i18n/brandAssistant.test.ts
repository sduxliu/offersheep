import { afterEach, describe, expect, it } from 'vitest';
import { brandAssistant, replaceCjkAware, setLocale, t } from './index';

afterEach(() => setLocale('zh-CN'));

describe('brandAssistant', () => {
  it('renames standalone Pilot and drops spaces next to Chinese text', () => {
    expect(brandAssistant('Haru 是 Pilot 的轻量窗口', 'zh-CN')).toBe('Haru 是求职助手的轻量窗口');
    expect(brandAssistant('会展开到 Pilot。对话不会丢失。', 'zh-CN')).toBe('会展开到求职助手。对话不会丢失。');
    expect(brandAssistant('Pilot · OfferSheep 领航员', 'zh-CN')).toBe('求职助手 · OfferSheep 领航员');
  });

  it('keeps compound names such as OfferPilot untouched', () => {
    expect(brandAssistant('OfferPilot 与 PilotMascot', 'zh-CN')).toBe('OfferPilot 与 PilotMascot');
  });

  it('uses the English name and keeps spacing in English copy', () => {
    expect(brandAssistant('Open Pilot to review', 'en-US')).toBe('Open Job Assistant to review');
  });
});

describe('t', () => {
  it('applies the assistant name before interpolating user values', () => {
    expect(t('Pilot')).toBe('求职助手');
    expect(t('{name}', { name: 'Pilot Corp' })).toBe('Pilot Corp');
  });

  it('follows the active locale', () => {
    setLocale('en-US');
    expect(t('Pilot')).toBe('Job Assistant');
  });
});

describe('replaceCjkAware', () => {
  it('replaces a companion name without leaving a space before Chinese text', () => {
    expect(replaceCjkAware('Haru 是求职助手的轻量窗口', '(?:Haru|咩咩)', '咩咩')).toBe('咩咩是求职助手的轻量窗口');
    expect(replaceCjkAware('Haru · 随时待命', '(?:Haru|咩咩)', 'Nova')).toBe('Nova · 随时待命');
  });
});
