import { normalizePilotMascotZoom, type PilotMascotAnimationLevel } from './pilotMascotPreference';
import {
  SHEEP_DESIGN_HEIGHT, SHEEP_DESIGN_WIDTH, drawSheep, drawSheepSprite, poseFor,
} from './sheepDrawing';
import sheepSpriteUrl from './assets/sheep-sprite.png';

export type PilotMascotActivity =
  | 'idle'
  | 'thinking'
  | 'preparing_voice'
  | 'speaking'
  | 'waiting_for_speech'
  | 'listening'
  | 'speech_paused'
  | 'transcribing'
  | 'reviewing_voice'
  | 'waiting_confirmation'
  | 'success'
  | 'error';

export interface PilotMascotRuntimeController {
  setActivity(activity: PilotMascotActivity): void;
  setZoom(zoom: number): void;
  dispose(): void;
}

export interface PilotMascotRuntime {
  mount(
    canvas: HTMLCanvasElement,
    signal?: AbortSignal,
    animationLevel?: PilotMascotAnimationLevel,
  ): Promise<PilotMascotRuntimeController>;
}

/** 同一画布上的挂载串行化：前一个实例释放后才挂载下一个。 */
export function serializePilotMascotRuntime(runtime: PilotMascotRuntime): PilotMascotRuntime {
  const canvasQueues = new WeakMap<HTMLCanvasElement, Promise<void>>();

  return {
    async mount(canvas, signal, animationLevel) {
      const previous = canvasQueues.get(canvas) ?? Promise.resolve();
      let releaseQueue!: () => void;
      const current = new Promise<void>((resolve) => {
        releaseQueue = resolve;
      });
      canvasQueues.set(canvas, current);
      await previous.catch(() => undefined);

      let mountedController: PilotMascotRuntimeController | undefined;
      const release = () => {
        if (mountedController) {
          mountedController.dispose();
          mountedController = undefined;
        }
        if (canvasQueues.get(canvas) === current) canvasQueues.delete(canvas);
        releaseQueue();
      };

      try {
        if (signal?.aborted) throw new DOMException('Mascot mount aborted', 'AbortError');
        mountedController = await runtime.mount(canvas, signal, animationLevel);
        if (signal?.aborted) throw new DOMException('Mascot mount aborted', 'AbortError');
        return {
          setActivity: (activity) => mountedController?.setActivity(activity),
          setZoom: (zoom) => mountedController?.setZoom(zoom),
          dispose: release,
        };
      } catch (error) {
        release();
        throw error;
      }
    },
  };
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function loadSprite(): HTMLImageElement | null {
  if (typeof Image === 'undefined') return null;
  const image = new Image();
  image.decoding = 'async';
  image.src = sheepSpriteUrl;
  return image;
}

function spriteReady(image: HTMLImageElement | null): image is HTMLImageElement {
  return image !== null && image.complete && image.naturalWidth > 0;
}

/** Canvas 2D 小羊运行时：无第三方模型与网络请求，关闭动画时只绘制静态帧。 */
export function createSheepPilotMascotRuntime(): PilotMascotRuntime {
  return {
    async mount(canvas, signal, animationLevel = 'full') {
      if (signal?.aborted) throw new DOMException('Mascot mount aborted', 'AbortError');
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('canvas_2d_unavailable');
      const level: PilotMascotAnimationLevel =
        animationLevel === 'full' && prefersReducedMotion() ? 'minimal' : animationLevel;
      let activity: PilotMascotActivity = 'idle';
      let activitySince = performance.now();
      let zoom = 1;
      let frame = 0;
      let disposed = false;
      const sprite = loadSprite();
      if (sprite && level === 'off') {
        sprite.addEventListener('load', () => {
          if (!disposed) render(performance.now());
        }, { once: true });
      }

      const render = (now: number) => {
        const ratio = window.devicePixelRatio || 1;
        const cssWidth = canvas.clientWidth || SHEEP_DESIGN_WIDTH;
        const cssHeight = canvas.clientHeight || SHEEP_DESIGN_HEIGHT;
        const width = Math.max(1, Math.round(cssWidth * ratio));
        const height = Math.max(1, Math.round(cssHeight * ratio));
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width;
          canvas.height = height;
        }
        const pose = poseFor(activity, (now - activitySince) / 1000, now / 1000, level);
        if (spriteReady(sprite)) drawSheepSprite(ctx, width, height, pose, zoom, sprite);
        else drawSheep(ctx, width, height, pose, zoom);
      };
      const loop = (now: number) => {
        if (disposed) return;
        render(now);
        frame = requestAnimationFrame(loop);
      };
      if (level === 'off') render(performance.now());
      else frame = requestAnimationFrame(loop);

      return {
        setActivity(next) {
          if (next === activity) return;
          activity = next;
          activitySince = performance.now();
          if (level === 'off') render(performance.now());
        },
        setZoom(next) {
          zoom = normalizePilotMascotZoom(next);
          if (level === 'off') render(performance.now());
        },
        dispose() {
          disposed = true;
          cancelAnimationFrame(frame);
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.clearRect(0, 0, canvas.width, canvas.height);
        },
      };
    },
  };
}

export const pilotMascotRuntime = serializePilotMascotRuntime(createSheepPilotMascotRuntime());
