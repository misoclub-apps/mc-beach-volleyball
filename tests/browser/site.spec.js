import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('選手検索 → 予定 → 大会 → 選手の往復', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('選手名', { exact: true }).fill('関 寛之');
  await expect(page.locator('.player-row')).toHaveCount(1);
  await page.locator('.player-link').click();
  await expect(page.locator('h1')).toContainText('関');
  await expect(page.locator('.appearance')).toHaveCount(2);
  await page.getByRole('link', { name: '相馬市長杯サテライト相馬大会', exact: true }).click();
  await expect(page.locator('.team')).not.toHaveCount(0);
  await expect(page.getByRole('heading', { name: '公式資料', exact: true })).toBeVisible();
  await page.locator('.team a').filter({ hasText: '関寛之' }).first().click();
  await expect(page.locator('h1')).toContainText('関');
});

test('お気に入り保存と再読み込み、空検索の回復', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('選手名', { exact: true }).fill('関寛之');
  await page.locator('[data-save]').click();
  await page.reload();
  await page.getByLabel('お気に入りだけ', { exact: true }).check();
  await expect(page.locator('.player-row')).toHaveCount(1);
  await page.getByLabel('選手名', { exact: true }).fill('見つからない名前');
  await expect(page.getByRole('button', { name: '絞り込みをリセット' })).toBeVisible();
  await page.getByRole('button', { name: '絞り込みをリセット' }).click();
  await expect(page.locator('.player-row')).not.toHaveCount(0);
});

test('大会検索と男女フィルターが機能する', async ({ page }) => {
  await page.goto('/#events');
  await page.getByLabel('大会名・会場', { exact: true }).fill('相馬');
  await expect(page.locator('.event-row')).toHaveCount(1);
  await page.goto('/#players');
  await page.getByRole('button', { name: '女子', exact: true }).click();
  await expect(page.locator('.player-identity .small-label').first()).toHaveText('女子');
});

test('通信失敗の回復案内', async ({ page }) => {
  await page.route('**/data/beach.json', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'データを読み込めませんでした' })).toBeVisible();
  await expect(page.getByRole('button', { name: '再読み込み' })).toBeVisible();
});

test('アクセシビリティの重大な違反がない', async ({ page }) => {
  for (const hash of ['players', 'events', 'about']) {
    await page.goto('/#' + hash);
    await expect(page.locator('h1')).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
    expect(results.violations).toEqual([]);
  }
});

for (const width of [320, 375, 414, 768, 1440]) test(`幅${width}pxで横にはみ出さない`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  for (const hash of ['players', 'events', 'about']) {
    await page.goto('/#' + hash);
    await expect(page.locator('h1')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
