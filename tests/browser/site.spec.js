import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
const snapshot = JSON.parse(
  readFileSync(new URL("../../public/data/beach.json", import.meta.url)),
);
const sakai = snapshot.players.find(
  (player) => player.name.replaceAll(" ", "") === "酒井春海",
);
const sakaiEvents = snapshot.events.filter((event) =>
  event.entries.some((entry) => entry.playerIds.includes(sakai.id)),
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
  ).toHaveCount(
    sakaiEvents.filter((event) => event.endDate >= snapshot.asOf).length,
  );
  await expect(page.locator(".past-results .appearance")).toHaveCount(
    sakaiEvents.filter((event) => event.endDate < snapshot.asOf).length,
  );
  const hiratsuka = page
    .locator(".past-results .appearance")
    .filter({ hasText: "平塚" });
  await expect(hiratsuka.locator(".appearance-result")).toHaveText(
    "最終順位9位",
  );
  await expect(
    hiratsuka.getByRole("link", { name: "公式の結果 PDF" }),
  ).toHaveAttribute("href", /#page=10$/);
  const soma = page
    .locator(".past-results .appearance")
    .filter({ hasText: "相馬市長杯ジャパンビーチバレーボールツアー2026" });
  await expect(soma.locator(".appearance-result")).toHaveText("最終順位5位");
  await expect(
    soma.getByRole("link", { name: "公式の結果 PDF" }),
  ).toHaveAttribute("href", /BVT2_soma_result_women_20260927\.pdf#page=2$/);
  await expect(
    soma.getByRole("link", { name: "公式の大会情報" }),
  ).toHaveAttribute("href", /entry-2493\.html$/);
  await page
    .getByRole("link", {
      name: "川崎市長杯 JVA第18回ビーチバレーボール大会",
      exact: true,
    })
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
  await page.getByLabel("選手名", { exact: true }).fill("");
  await expect(page.locator(".player-row h3").first()).toHaveText("酒井春海");
  await page.reload();
  await expect(page.locator(".player-row h3").first()).toHaveText("酒井春海");
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
  await page.getByLabel("大会名・会場", { exact: true }).fill("川崎市長杯");
  await expect(page.locator(".event-row")).toHaveCount(1);
  await page.goto("/#players");
  await page.getByRole("button", { name: "女子", exact: true }).click();
  await expect(
    page.locator(".player-identity .small-label").first(),
  ).toHaveText("女子");
});

test("海外大会は日本ペアだけを出場区分つきで表示する", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/#event/e-5d176050896885");
  await expect(
    page.getByRole("heading", { name: "FUTURESアランヤ大会" }),
  ).toBeVisible();
  await expect(page.locator(".team")).toHaveCount(4);
  await expect(
    page.locator(".team .badge").filter({ hasText: "本戦" }),
  ).toHaveCount(2);
  await expect(
    page.locator(".team .badge").filter({ hasText: "予選" }),
  ).toHaveCount(1);
  await expect(
    page.locator(".team .badge").filter({ hasText: "リザーブ" }),
  ).toHaveCount(1);
  await expect(
    page.getByText("日本ペアの試合日程は公式発表後に掲載します。", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.locator(".team").first().getByRole("link", { name: "公式チーム表" }),
  ).toHaveAttribute("href", /volleyballworld\.com/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("終了済み海外大会は日本ペアの順位と公式確認済み試合を表示する", async ({
  page,
}) => {
  await page.goto("/#event/e-f30967f7b13b30");
  await expect(
    page.getByRole("heading", { name: "CHALLENGEブバネーシュワル大会" }),
  ).toBeVisible();
  await expect(page.locator(".team")).toHaveCount(3);
  await expect(page.locator(".team .result-field")).toHaveCount(3);
  await expect(
    page.locator(".team").first().getByRole("link", { name: "結果ページ" }),
  ).toHaveAttribute("href", /volleyballworld\.com\/.+\/standings\/women\/$/);
  await expect(page.locator(".international-match")).toHaveCount(8);
  await expect(page.locator(".international-matches")).toContainText("USA");
  await expect(
    page
      .locator(".international-match")
      .first()
      .getByRole("link", { name: "公式試合ページ" }),
  ).toHaveAttribute("href", /volleyballworld\.com\/.+\/schedule\/\d+\/$/);
});

test("空白を含む公式の会場ラベルも表示する", async ({ page }) => {
  await page.goto("/#event/e-b9d8aa90fc8676");
  await expect(page.locator(".event-meta")).toContainText(
    "静岡県浜松市・遠州灘海浜公園江之島ビーチコート",
  );
});

test("個人ページの1位表示は色を残して星を付けない", async ({ page }) => {
  await page.goto("/#player/p-54316126a8a75f");
  const soma = page
    .locator(".past-results .appearance")
    .filter({ hasText: "相馬市長杯サテライト相馬" })
    .first();
  await expect(soma.locator(".appearance-result.is-winner")).toHaveText(
    "最終順位1位",
  );
  await expect(soma.locator(".appearance-result")).not.toContainText("★");
});

test("スマホでも次回大会カードと公式プロフィール画像を表示する", async ({
  page,
}) => {
  await page.route("https://www.jbv.jp/players/**", (route) =>
    route.fulfill({
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
        "base64",
      ),
    }),
  );
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
  await expect(page.locator(".event-row")).toHaveCount(
    snapshot.events.filter((event) => event.endDate < snapshot.asOf).length,
  );
  expect(
    await page.locator(".event-row .badge.result").count(),
  ).toBeGreaterThan(0);
  await page.getByLabel("大会名・会場").fill("第4戦 立川立飛大会");
  await page
    .locator(".event-row")
    .filter({ hasText: "第4戦 立川立飛大会" })
    .click();
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
  await expect(page.locator(".team .result-field").first()).toHaveText("1位★");
  await expect(
    page.locator(".team").first().getByRole("link", { name: "結果 PDF" }),
  ).toHaveAttribute("href", /\.pdf(?:#page=\d+)?$/);
  await expect(
    page.locator(".team .result-field.is-winner").first(),
  ).toBeVisible();
});

test("個人順位の大会も選手ページへ辿れる", async ({ page }) => {
  await page.goto("/#events");
  await page.locator("#event-period").selectOption("past");
  await page.locator("#event-search").fill("横浜キング");
  await page.locator(".event-row").click();
  await expect(
    page.getByRole("heading", { name: "最終順位・選手" }),
  ).toBeVisible();
  await expect(
    page.locator(".section-heading").filter({ hasText: "32 選手" }),
  ).toBeVisible();
  await page.locator(".team a").first().click();
  await expect(
    page
      .locator(".appearance .partner")
      .filter({ hasText: "個人順位" })
      .first(),
  ).toBeVisible();
});

test("最終確認を終えた大会は選手とのリンクを残して未確認と表示する", async ({ page }) => {
  const fixture = structuredClone(snapshot);
  const event = fixture.events.find((item) => item.id === "e-531409aa8438dc");
  event.entries[0].status = "resultUnavailable";
  delete event.entries[0].rank;
  delete event.entries[0].resultLabel;
  event.entryStatus = "resultUnavailable";
  event.resultCoverage = "公式の最終順位を確認できませんでした。";
  await page.route("**/data/beach.json", (route) => route.fulfill({ json: fixture }));
  await page.goto(`/#event/${event.id}`);
  await expect(page.getByRole("heading", { name: "試合結果" })).toBeVisible();
  await expect(page.locator(".event-results")).toContainText("最終順位未確認");
  await expect(page.locator(".team")).toHaveCount(1);
  await page.locator(".team a").first().click();
  await expect(page.locator(".past-results .appearance").filter({ hasText: event.name })).toContainText("最終順位未確認");
});
