import { execFileSync } from 'node:child_process';

/**
 * 上游 offerPilot 的「历史门禁」测试会审计特定提交区间。OfferSheep 以全新 git 历史
 * 发布，这些提交不存在；此时跳过门禁，同步上游历史后会自动恢复执行。
 */
export function hasGitCommits(...shas: string[]): boolean {
  try {
    for (const sha of shas) {
      execFileSync('git', ['cat-file', '-e', `${sha}^{commit}`], { stdio: 'ignore' });
    }
    return true;
  } catch {
    return false;
  }
}
