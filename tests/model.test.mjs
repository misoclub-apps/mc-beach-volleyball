import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  normalize,
  todayJst,
  filterPlayers,
  filterEvents,
  appearances,
  safeLink,
  escapeHtml,
} from "../model.js";
const data = JSON.parse(
  readFileSync(new URL("../public/data/beach.json", import.meta.url)),
);
test("名前の空白・全半角・異体字を吸収する", () =>
  assert.equal(normalize("髙橋　大地"), normalize("高橋大地")));
test("日本時間の日付で予定を判定する", () =>
  assert.equal(todayJst(new Date("2026-09-21T16:00:00Z")), "2026-09-22"));
test("相馬・高萩の実データから関寛之の出場予定を引ける", () => {
  const [p] = filterPlayers(data, {
    query: "関 寛之",
    upcoming: true,
    today: data.asOf,
  });
  assert.ok(p);
  const names = appearances(data, p.id).map((a) => a.event.name);
  assert.ok(names.some((n) => n.includes("相馬")));
  assert.ok(names.some((n) => n.includes("高萩")));
});
test("補欠のみの選手を出場予定フィルターに混ぜない", () => {
  const d = {
    players: [{ id: "p", name: "選手", aliases: [], gender: "men" }],
    events: [
      {
        startDate: "2026-10-01",
        endDate: "2026-10-01",
        entries: [{ playerIds: ["p", "q"], status: "reserve" }],
      },
    ],
  };
  assert.equal(
    filterPlayers(d, { upcoming: true, today: "2026-09-22" }).length,
    0,
  );
  assert.equal(filterPlayers(d, { upcoming: false }).length, 1);
});
test("開催中止は出場予定に表示しない", () => {
  const d = structuredClone(data);
  d.events.forEach((e) => (e.cancelled = true));
  assert.equal(
    filterPlayers(d, { upcoming: true, today: data.asOf }).length,
    0,
  );
});
test("女子・お気に入り・名前を同時に絞り込める", () => {
  const p = data.players.find((p) => p.gender === "women");
  assert.equal(
    filterPlayers(data, {
      gender: "women",
      favorites: true,
      saved: [p.id],
      query: p.name,
    }).length,
    1,
  );
  assert.equal(
    filterPlayers(data, { gender: "men", favorites: true, saved: [p.id] })
      .length,
    0,
  );
});
test("外部ソースにHTMLやjavascript URLがあっても実行しない", () => {
  assert.equal(safeLink("javascript:alert(1)"), "#");
  assert.equal(
    escapeHtml('<img onerror="x">'),
    "&lt;img onerror=&quot;x&quot;&gt;",
  );
});
test("出典・選手参照・日程が整合し、終了済み大会が含まれない", () => {
  const ids = new Set(data.players.map((p) => p.id));
  for (const e of data.events) {
    assert.ok(e.startDate && e.endDate >= e.startDate);
    assert.ok(e.endDate >= data.asOf);
    assert.match(e.sourceUrl, /^https:\/\//);
    const seen = new Set();
    for (const entry of e.entries) {
      assert.equal(entry.playerIds.length, 2);
      assert.match(entry.sourceUrl, /^https:\/\//);
      for (const id of entry.playerIds) {
        assert.ok(ids.has(id));
        assert.ok(!seen.has(id));
        seen.add(id);
      }
    }
  }
  assert.ok(filterEvents(data, { query: "相馬", today: data.asOf }).length);
});
