import type { PilotMascotActivity } from './mascotRuntime';
import type { PilotMascotAnimationLevel } from './pilotMascotPreference';

/**
 * 原创矢量小羊「咩咩」：白色卷毛、粉色圆框眼镜、粉色小角/耳内/蹄子。
 * 造型参考用户提供的三视图正面，全部由 Canvas 2D 路径绘制，不依赖第三方模型资源。
 */

export interface SheepPose {
  /** 0~1，1 为完全睁眼；低于 0.25 绘制为闭眼弧线 */
  eyeOpen: number;
  /** 0~1，嘴巴张开程度 */
  mouthOpen: number;
  /** 头部旋转（弧度），绕脖子转动 */
  headTilt: number;
  /** 整体竖直位移（设计坐标，负值向上） */
  bob: number;
  /** 整体水平位移（设计坐标） */
  shake: number;
  /** 身体呼吸缩放 */
  breathe: number;
  /** 耳朵上扬（弧度） */
  earLift: number;
  /** 头顶装饰 */
  accent: 'none' | 'thinking' | 'success' | 'error';
  /** 装饰动画相位 0~1 */
  accentPhase: number;
}

export const SHEEP_DESIGN_WIDTH = 200;
export const SHEEP_DESIGN_HEIGHT = 300;

const OUTLINE = '#b07468';
const WOOL = '#fffaf6';
const WOOL_SHADE = '#fbe6e2';
const FACE = '#fffdfb';
const PINK = '#f3aaa0';
const PINK_DEEP = '#e48a80';
const EYE = '#5b2b25';
const EYE_LOW = '#b9524a';

export const restingPose: SheepPose = {
  eyeOpen: 1,
  mouthOpen: 0,
  headTilt: 0,
  bob: 0,
  shake: 0,
  breathe: 1,
  earLift: 0,
  accent: 'none',
  accentPhase: 0,
};

const THINKING: ReadonlySet<PilotMascotActivity> = new Set([
  'thinking', 'preparing_voice', 'transcribing', 'reviewing_voice',
]);
const LISTENING: ReadonlySet<PilotMascotActivity> = new Set([
  'listening', 'waiting_for_speech', 'speech_paused',
]);

/** 由活动状态与时间推导姿态；纯函数，便于测试。 */
export function poseFor(
  activity: PilotMascotActivity,
  elapsed: number,
  time: number,
  level: PilotMascotAnimationLevel,
): SheepPose {
  const pose: SheepPose = { ...restingPose };
  if (level === 'off') return pose;
  pose.eyeOpen = time % 3.6 < 0.14 ? 0.1 : 1;
  pose.breathe = 1 + 0.012 * Math.sin(time * 2.2);
  if (level === 'minimal') return pose;
  pose.bob = 2.2 * Math.sin(time * 1.7);
  if (THINKING.has(activity)) {
    pose.headTilt = 0.07 * Math.sin(time * 1.3);
    pose.accent = 'thinking';
    pose.accentPhase = (time % 1.2) / 1.2;
  } else if (activity === 'speaking') {
    pose.mouthOpen = 0.5 + 0.5 * Math.sin(time * 14);
    pose.bob = -3 * Math.abs(Math.sin(time * 5));
  } else if (LISTENING.has(activity)) {
    pose.earLift = 0.32;
    pose.headTilt = -0.05;
  } else if (activity === 'waiting_confirmation') {
    pose.headTilt = 0.1 * Math.sin(time * 2);
  } else if (activity === 'success') {
    const hop = (elapsed % 0.9) / 0.9;
    pose.bob = -56 * hop * (1 - hop);
    pose.eyeOpen = 0.15;
    pose.accent = 'success';
    pose.accentPhase = time % 1;
  } else if (activity === 'error') {
    pose.shake = elapsed < 0.6 ? 4 * Math.sin(elapsed * 40) : 0;
    pose.accent = 'error';
    pose.accentPhase = (time % 1.5) / 1.5;
  }
  return pose;
}

function ellipse(
  ctx: CanvasRenderingContext2D, x: number, y: number, rx: number, ry: number, rotation = 0,
): void {
  ctx.beginPath();
  ctx.ellipse(x, y, rx, ry, rotation, 0, Math.PI * 2);
}

/** 卷毛云朵：先描全部小圆再整体填充，只留下外轮廓。 */
function woolCloud(
  ctx: CanvasRenderingContext2D, cx: number, cy: number, rx: number, ry: number,
  puffs: number, radius: number,
): void {
  const points: Array<[number, number]> = [];
  for (let index = 0; index < puffs; index += 1) {
    const angle = (index / puffs) * Math.PI * 2;
    points.push([cx + Math.cos(angle) * rx, cy + Math.sin(angle) * ry]);
  }
  ctx.lineWidth = 3;
  ctx.strokeStyle = OUTLINE;
  for (const [x, y] of points) {
    ellipse(ctx, x, y, radius, radius);
    ctx.stroke();
  }
  ctx.fillStyle = WOOL;
  for (const [x, y] of points) {
    ellipse(ctx, x, y, radius - 1.5, radius - 1.5);
    ctx.fill();
  }
  ellipse(ctx, cx, cy, rx, ry);
  ctx.fill();
}

function outlined(ctx: CanvasRenderingContext2D, fill: string, width = 2.5): void {
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.lineWidth = width;
  ctx.strokeStyle = OUTLINE;
  ctx.stroke();
}

function drawBody(ctx: CanvasRenderingContext2D, breathe: number): void {
  ctx.globalAlpha = 0.12;
  ctx.fillStyle = OUTLINE;
  ellipse(ctx, 100, 292, 50, 6);
  ctx.fill();
  ctx.globalAlpha = 1;
  for (const x of [82, 118]) {
    ellipse(ctx, x, 266, 15, 21);
    outlined(ctx, WOOL);
    ellipse(ctx, x, 283, 13, 7);
    outlined(ctx, PINK);
  }
  ctx.save();
  ctx.translate(100, 212);
  ctx.scale(breathe, breathe);
  ctx.translate(-100, -212);
  for (const side of [-1, 1]) {
    const x = 100 + side * 50;
    ellipse(ctx, x, 210, 13, 20, side * 0.25);
    outlined(ctx, WOOL);
    ellipse(ctx, x + side * 2, 229, 9, 7);
    outlined(ctx, PINK);
  }
  woolCloud(ctx, 100, 212, 44, 38, 14, 17);
  ctx.globalAlpha = 0.55;
  ctx.fillStyle = WOOL_SHADE;
  ellipse(ctx, 100, 224, 28, 22);
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.restore();
}

function drawHorn(ctx: CanvasRenderingContext2D, x: number, side: number): void {
  ctx.beginPath();
  ctx.moveTo(x - 8, 66);
  ctx.quadraticCurveTo(x - 4 + side * 2, 44, x + side * 6, 40);
  ctx.quadraticCurveTo(x + 6 + side * 2, 54, x + 9, 66);
  ctx.closePath();
  outlined(ctx, PINK);
}

function drawEye(ctx: CanvasRenderingContext2D, x: number, open: number): void {
  if (open < 0.25) {
    ctx.beginPath();
    ctx.arc(x, 126, 6, Math.PI * 1.15, Math.PI * 1.85);
    ctx.lineWidth = 2.6;
    ctx.strokeStyle = EYE;
    ctx.stroke();
    return;
  }
  ellipse(ctx, x, 124, 6.5, 8.2 * open);
  ctx.fillStyle = EYE;
  ctx.fill();
  ellipse(ctx, x, 124 + 3.5 * open, 4.6, 3.6 * open);
  ctx.fillStyle = EYE_LOW;
  ctx.fill();
  ctx.fillStyle = '#ffffff';
  ellipse(ctx, x - 2.4, 120.5, 2.5, 2.5);
  ctx.fill();
  ellipse(ctx, x + 2.2, 127, 1.2, 1.2);
  ctx.fill();
}

function drawHead(ctx: CanvasRenderingContext2D, pose: SheepPose): void {
  ctx.save();
  ctx.translate(100, 168);
  ctx.rotate(pose.headTilt);
  ctx.translate(-100, -168);
  for (const side of [-1, 1]) {
    const tilt = side * (0.55 - pose.earLift);
    ellipse(ctx, 100 + side * 60, 114, 27, 13, tilt);
    outlined(ctx, WOOL);
    ellipse(ctx, 100 + side * 62, 115, 17, 7, tilt);
    ctx.fillStyle = PINK;
    ctx.fill();
  }
  drawHorn(ctx, 72, -1);
  drawHorn(ctx, 128, 1);
  woolCloud(ctx, 100, 102, 48, 44, 16, 20);
  ellipse(ctx, 100, 126, 38, 29);
  ctx.fillStyle = FACE;
  ctx.fill();
  ctx.globalAlpha = 0.55;
  ctx.fillStyle = PINK;
  for (const x of [68, 132]) {
    ellipse(ctx, x, 140, 8, 4.2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  drawEye(ctx, 82, pose.eyeOpen);
  drawEye(ctx, 118, pose.eyeOpen);
  ctx.lineWidth = 3;
  ctx.strokeStyle = PINK_DEEP;
  for (const x of [82, 118]) {
    ellipse(ctx, x, 124, 15, 15);
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.moveTo(97, 123);
  ctx.quadraticCurveTo(100, 119, 103, 123);
  ctx.moveTo(67, 121);
  ctx.lineTo(57, 117);
  ctx.moveTo(133, 121);
  ctx.lineTo(143, 117);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(97.5, 139);
  ctx.quadraticCurveTo(100, 136.5, 102.5, 139);
  ctx.quadraticCurveTo(100, 142, 97.5, 139);
  ctx.fillStyle = PINK_DEEP;
  ctx.fill();
  ctx.lineWidth = 1.8;
  ctx.strokeStyle = OUTLINE;
  if (pose.mouthOpen > 0.05) {
    ellipse(ctx, 100, 147, 4, 1.8 + 3.8 * pose.mouthOpen);
    ctx.fillStyle = '#c46a62';
    ctx.fill();
  } else {
    ctx.beginPath();
    ctx.arc(97, 143, 3, 0.15 * Math.PI, 0.85 * Math.PI);
    ctx.moveTo(106, 143.8);
    ctx.arc(103, 143, 3, 0.15 * Math.PI, 0.85 * Math.PI);
    ctx.stroke();
  }
  ctx.restore();
}

function drawStar(ctx: CanvasRenderingContext2D, x: number, y: number, size: number): void {
  ctx.beginPath();
  ctx.moveTo(x, y - size);
  ctx.quadraticCurveTo(x, y, x + size, y);
  ctx.quadraticCurveTo(x, y, x, y + size);
  ctx.quadraticCurveTo(x, y, x - size, y);
  ctx.quadraticCurveTo(x, y, x, y - size);
  ctx.fill();
}

function drawAccent(ctx: CanvasRenderingContext2D, pose: SheepPose): void {
  if (pose.accent === 'thinking') {
    ctx.fillStyle = PINK_DEEP;
    for (let index = 0; index < 3; index += 1) {
      const lift = Math.max(0, Math.sin((pose.accentPhase - index * 0.18) * Math.PI * 2)) * 4;
      ellipse(ctx, 146 + index * 10, 44 - lift, 3.2, 3.2);
      ctx.fill();
    }
  } else if (pose.accent === 'success') {
    ctx.fillStyle = '#f5c04a';
    ctx.globalAlpha = 0.6 + 0.4 * Math.sin(pose.accentPhase * Math.PI * 2);
    drawStar(ctx, 40, 50, 7);
    drawStar(ctx, 160, 40, 9);
    ctx.globalAlpha = 1;
  } else if (pose.accent === 'error') {
    const y = 72 + pose.accentPhase * 10;
    ctx.beginPath();
    ctx.moveTo(152, y - 8);
    ctx.quadraticCurveTo(158, y, 152, y + 4);
    ctx.quadraticCurveTo(146, y, 152, y - 8);
    ctx.fillStyle = '#9fd3f0';
    ctx.fill();
  }
}

/** 设计坐标系变换：底部居中、等比适配，并叠加整体位移。 */
function applyDesignTransform(
  ctx: CanvasRenderingContext2D, width: number, height: number, pose: SheepPose, zoom: number,
): void {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const fit = Math.min(width / SHEEP_DESIGN_WIDTH, height / SHEEP_DESIGN_HEIGHT);
  const scale = Math.min(fit * 0.98, fit * 0.86 * zoom);
  const offsetX = (width - SHEEP_DESIGN_WIDTH * scale) / 2 + pose.shake * scale;
  const offsetY = height - SHEEP_DESIGN_HEIGHT * scale + pose.bob * scale;
  ctx.setTransform(scale, 0, 0, scale, offsetX, offsetY);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
}

/**
 * 用用户提供的小羊插画（透明底精灵图）绘制一帧：整体呼吸、摇摆、跳跃与头顶装饰；
 * 精灵图是静态插画，眨眼与张嘴只在矢量兜底形象中呈现。
 */
export function drawSheepSprite(
  ctx: CanvasRenderingContext2D, width: number, height: number, pose: SheepPose, zoom: number,
  sprite: { naturalWidth: number; naturalHeight: number } & CanvasImageSource,
): void {
  applyDesignTransform(ctx, width, height, pose, zoom);
  ctx.globalAlpha = 0.12;
  ctx.fillStyle = OUTLINE;
  ellipse(ctx, 100, 292, 50, 6);
  ctx.fill();
  ctx.globalAlpha = 1;
  const ratio = Math.min(196 / sprite.naturalWidth, 288 / sprite.naturalHeight);
  const spriteWidth = sprite.naturalWidth * ratio;
  const spriteHeight = sprite.naturalHeight * ratio;
  ctx.save();
  ctx.translate(100, 290);
  ctx.rotate(pose.headTilt * 0.6);
  ctx.scale(1 + (pose.breathe - 1) * 0.5, pose.breathe);
  ctx.drawImage(sprite, -spriteWidth / 2, -spriteHeight, spriteWidth, spriteHeight);
  ctx.restore();
  drawAccent(ctx, pose);
}

/** 在画布像素尺寸内按「底部居中、等比适配」绘制一帧矢量小羊（精灵图加载前的兜底）。 */
export function drawSheep(
  ctx: CanvasRenderingContext2D, width: number, height: number, pose: SheepPose, zoom = 1,
): void {
  applyDesignTransform(ctx, width, height, pose, zoom);
  drawBody(ctx, pose.breathe);
  drawHead(ctx, pose);
  drawAccent(ctx, pose);
}
