// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { drawSheep, drawSheepSprite, poseFor, restingPose } from './sheepDrawing';
import { createSheepPilotMascotRuntime } from './mascotRuntime';

function recordingContext() {
  const calls: string[] = [];
  const ctx = new Proxy({} as Record<string, unknown>, {
    get(target, key: string) {
      if (key in target) return target[key];
      return (..._args: unknown[]) => { calls.push(key); };
    },
    set(target, key: string, value) {
      target[key] = value;
      return true;
    },
  });
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
}

describe('poseFor', () => {
  it('keeps a static resting pose when animation is off', () => {
    expect(poseFor('speaking', 1, 5, 'off')).toEqual(restingPose);
  });

  it('only blinks and breathes in minimal mode', () => {
    const pose = poseFor('success', 0.3, 0.05, 'minimal');
    expect(pose.eyeOpen).toBe(0.1);
    expect(pose.accent).toBe('none');
    expect(pose.bob).toBe(0);
  });

  it('maps activities to distinct expressions in full mode', () => {
    expect(poseFor('thinking', 0, 1, 'full').accent).toBe('thinking');
    expect(poseFor('listening', 0, 1, 'full').earLift).toBeGreaterThan(0);
    expect(poseFor('success', 0.45, 1, 'full').bob).toBeLessThan(0);
    expect(poseFor('error', 0.3, 1, 'full').accent).toBe('error');
    expect(poseFor('speaking', 0, 0.1, 'full').mouthOpen).toBeGreaterThan(0);
  });
});

describe('drawSheep', () => {
  it('draws the user illustration sprite when it is available', () => {
    const { ctx, calls } = recordingContext();
    const sprite = { naturalWidth: 742, naturalHeight: 893 } as unknown as HTMLImageElement;
    drawSheepSprite(ctx, 238, 370, { ...restingPose, accent: 'thinking' }, 1, sprite);
    expect(calls).toContain('drawImage');
    expect(calls.filter((name) => name === 'drawImage')).toHaveLength(1);
  });
  it('clears the frame and draws with paths only', () => {
    const { ctx, calls } = recordingContext();
    drawSheep(ctx, 238, 370, { ...restingPose, accent: 'success' }, 1);
    expect(calls[0]).toBe('setTransform');
    expect(calls).toContain('clearRect');
    expect(calls).toContain('ellipse');
    expect(calls).not.toContain('drawImage');
  });
});

describe('createSheepPilotMascotRuntime', () => {
  it('rejects canvases without a 2D context so the dock falls back', async () => {
    const canvas = { getContext: () => null } as unknown as HTMLCanvasElement;
    await expect(createSheepPilotMascotRuntime().mount(canvas)).rejects.toThrow('canvas_2d_unavailable');
  });

  it('renders a single static frame when animation is off and disposes cleanly', async () => {
    const { ctx, calls } = recordingContext();
    const canvas = { getContext: () => ctx, clientWidth: 116, clientHeight: 174, width: 0, height: 0 } as unknown as HTMLCanvasElement;
    const raf = vi.spyOn(globalThis, 'requestAnimationFrame');
    const controller = await createSheepPilotMascotRuntime().mount(canvas, undefined, 'off');
    expect(raf).not.toHaveBeenCalled();
    expect(calls).toContain('ellipse');
    controller.setActivity('thinking');
    controller.dispose();
    expect(calls[calls.length - 1]).toBe('clearRect');
    raf.mockRestore();
  });
});
