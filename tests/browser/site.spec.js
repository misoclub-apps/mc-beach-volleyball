import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
const snapshot = JSON.parse(
  readFileSync(new URL("../../public/data/beach.json", import.meta.url)),
);
// Keep the snapshot tests reproducible after the real calendar advances.
test.beforeEach(async ({ page }) => {
  await page.clock.install({
    time: new Date(`${snapshot.asOf}T03:00:00+09:00`),
  });
});

test("選手検索 → 予定 → 大会 → 選手の往復", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("選手名", { exact: true }).fill("酒井 春海");
  await expect(page.locator(".player-row")).toHaveCount(1);
  await page.locator(".player-link").click();
  await expect(page.locator("h1")).toContainText("酒井");
  await expect(
    page.locator(".appearance").filter({ hasText: "開催予定" }),
  ).toHaveCount(2);
  await expect(page.locator(".past-results .appearance")).toHaveCount(5);
  const hiratsuka = page
    .locator(".past-results .appearance")
    .filter({ hasText: "平塚" });
  await expect(hiratsuka.locator(".badge.result")).toHaveText("9位");
  await expect(
    hiratsuka.getByRole("link", { name: "公式の結果 PDF" }),
  ).toHaveAttribute("href", /#page=10$/);
  await page
    .getByRole("link", { name: "相馬市長杯サテライト相馬大会", exact: true })
    .click();
  await expect(page.locator(".team")).not.toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "大会資料", exact: true }),
  ).toBeVisible();
  await page.locator(".team a").filter({ hasText: "酒井春海" }).first().click();
  await expect(page.locator("h1")).toContainText("酒井");
});

test("お気に入り保存と再読み込み、空検索の回復", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("選手名", { exact: true }).fill("酒井春海");
  await page.locator("[data-save]").click();
  await page.reload();
  await page.getByLabel("お気に入りだけ", { exact: true }).check();
  await expect(page.locator(".player-row")).toHaveCount(1);
  await page.getByLabel("選手名", { exact: true }).fill("見つからない名前");
  await expect(
    page.getByRole("button", { name: "絞り込みをリセット" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "絞り込みをリセット" }).click();
  await expect(page.locator(".player-row")).not.toHaveCount(0);
});

test("大会検索と男女フィルターが機能する", async ({ page }) => {
  await page.goto("/#events");
  await page.getByLabel("大会名・会場", { exact: true }).fill("相馬");
  await expect(page.locator(".event-row")).toHaveCount(1);
  await page.goto("/#players");
  await page.getByRole("button", { name: "女子", exact: true }).click();
  await expect(
    page.locator(".player-identity .small-label").first(),
  ).toHaveText("女子");
});

test("スマホでも次回大会カードと公式プロフィール画像を表示する", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/");
  await expect(page.locator(".next-event")).toBeVisible();
  const searchCenters = await page.locator(".search-box").evaluate((box) => {
    const input = box.querySelector("input").getBoundingClientRect();
    const icon = box.querySelector("svg").getBoundingClientRect();
    return [input.top + input.height / 2, icon.top + icon.height / 2];
  });
  expect(Math.abs(searchCenters[0] - searchCenters[1])).toBeLessThan(1);
  await page.getByLabel("選手名", { exact: true }).fill("酒井春海");
  const photo = page.locator(".player-row [data-profile-photo]");
  await expect(photo).toBeVisible();
  await expect(photo).toHaveJSProperty("complete", true);
  expect(await photo.evaluate((image) => image.naturalWidth)).toBeGreaterThan(
    0,
  );
  await page.locator(".player-link").click();
  const largePhoto = page.locator(".profile-heading .player-photo.large");
  await expect(largePhoto.locator("[data-profile-photo]")).toBeVisible();
  const photoBox = await largePhoto.boundingBox();
  expect(photoBox.height).toBeGreaterThan(photoBox.width);
  expect(photoBox.height / photoBox.width).toBeCloseTo(1.5, 1);
});

test("通信失敗の回復案内", async ({ page }) => {
  await page.route("**/data/beach.json", (route) => route.abort());
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "データを読み込めませんでした" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "再読み込み" })).toBeVisible();
});

test("アクセシビリティの重大な違反がない", async ({ page }) => {
  for (const hash of [
    "players",
    "events",
    "about",
    "player/p-bd2ce333aca5e6",
  ]) {
    await page.goto("/#" + hash);
    await expect(page.locator("h1")).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(results.violations).toEqual([]);
  }
});

for (const width of [320, 375, 414, 768, 1440])
  test(`幅${width}pxで横にはみ出さない`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const hash of [
      "players",
      "events",
      "about",
      "player/p-bd2ce333aca5e6",
    ]) {
      await page.goto("/#" + hash);
      await expect(page.locator("h1")).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
  });

test("過去大会は期間で絞り込めて結果とペアを辿れる", async ({ page }) => {
  await page.goto("/#events");
  await page.getByLabel("表示期間").selectOption("past");
  await expect(page.locator(".event-row")).toHaveCount(6);
  await expect(page.locator(".event-row .badge.result")).toHaveCount(6);
  await page.getByLabel("大会名・会場").fill("立川");
  await page.locator(".event-row").click();
  await expect(
    page.getByRole("heading", { name: "試合結果", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "最終順位・ペア" }),
  ).toBeVisible();
  const resultPanel = page.locator(".event-results");
  await expect(resultPanel).toContainText("女子 優勝");
  await expect(resultPanel).toContainText("辻村りこ");
  await expect(resultPanel).toContainText("西堀健実");
  await expect(
    resultPanel.getByRole("link", { name: /女子結果 6月26日/ }),
  ).toHaveAttribute("href", /tachikawa_result_women0626\.pdf$/);
  await expect(
    page.getByText("男子の最終順位表は確認できていません。", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".team .badge.result").first()).toHaveText("1位");
});
