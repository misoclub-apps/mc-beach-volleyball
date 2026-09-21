import {
  appearances,
  escapeHtml as h,
  filterEvents,
  filterPlayers,
  isUpcoming,
  safeLink,
  todayJst,
} from "./model.js";

const main = document.querySelector("main");
let data;
let saved = [];
try {
  const s = JSON.parse(localStorage.getItem("beach-note:favorites") || "[]");
  if (Array.isArray(s)) saved = s;
} catch {
  /* Private browsing can disable storage. */
}
const filters = { query: "", gender: "", upcoming: true, favorites: false };
const eventFilters = { query: "", category: "", period: "upcoming" };
const external = (url, label, cls = "") =>
  `<a class="external ${cls}" href="${safeLink(url)}" target="_blank" rel="noopener noreferrer">${h(label)} <span aria-hidden="true">↗</span></a>`;
const genderName = (gender) => (gender === "men" ? "男子" : "女子");
const stamp = (value) =>
  new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
const date = (value) =>
  value
    ? `${Number(value.slice(5, 7))}/${Number(value.slice(8, 10))}`
    : "日程確認中";
const range = (event) =>
  event.startDate
    ? date(event.startDate) +
      (event.endDate !== event.startDate ? ` — ${date(event.endDate)}` : "")
    : "日程確認中";
const badge = (entry, event) =>
  `<span class="badge ${entry.status === "completed" ? "result" : entry.status === "entered" ? "" : "sand"}">${h(entry.status === "completed" ? entry.resultLabel : { entered: event && !isUpcoming(event) ? "名簿掲載" : "出場予定", reserve: "補欠", withdrawn: "欠場" }[entry.status] || "確認中")}</span>`;
const favorite = (p) =>
  `<button class="favorite ${saved.includes(p.id) ? "is-saved" : ""}" data-save="${p.id}" aria-pressed="${saved.includes(p.id)}" aria-label="${h(p.name)}をお気に入り${saved.includes(p.id) ? "から削除" : "に追加"}">${saved.includes(p.id) ? "★" : "☆"}</button>`;
const portrait = (p, large = false) =>
  `<div class="player-photo${large ? " large" : ""}"><span aria-hidden="true">${h(p.name.replace(/\s/g, "").slice(0, 1))}</span>${p.imageUrl ? `<img src="${safeLink(p.imageUrl)}" alt="${large ? `${h(p.name)}の公式プロフィール写真` : ""}" loading="lazy" referrerpolicy="no-referrer" data-profile-photo>` : ""}</div>`;
const empty = (
  text,
  action = '<a class="button" href="#events">大会を探す</a>',
) =>
  `<div class="empty"><span aria-hidden="true">—</span><h2>${text}</h2>${action}</div>`;

function freshness() {
  const age =
    (Date.now() - Date.parse(data.checkedAt || data.generatedAt)) / 86400000;
  return `<div class="freshness"><span>公式情報の最終取得 <time datetime="${data.checkedAt || data.generatedAt}">${stamp(data.checkedAt || data.generatedAt)}</time></span><a href="#about">掲載範囲について ↗</a></div>${age > 7 ? '<p class="notice">最終更新から7日以上経過しています。変更の有無は各大会の公式情報をご確認ください。</p>' : ""}`;
}

function home() {
  const next =
    data.events.find((e) => isUpcoming(e) && e.entries.length) ||
    data.events.find((e) => isUpcoming(e));
  main.innerHTML = `<section class="intro"><div><p class="eyebrow">BEACH VOLLEYBALL / ${data.year}</p><h1>気になる選手の、<br>次のコートへ。</h1><p class="intro-copy">選手から、出場大会と日程をひと目で。<br>公式サイトに散らばる情報を、このノートに。</p></div>${next ? `<a class="next-event" href="#event/${next.id}"><span class="eyebrow">NEXT ON THE SAND</span><span class="next-date">${range(next)}</span><strong>${h(next.name)}</strong><span class="next-place">${h(next.venue)}</span><span class="next-link">大会を見る <span>↗</span></span></a>` : ""}</section>${freshness()}
    <section class="directory" aria-labelledby="directory-title"><aside class="filters"><p class="eyebrow">PLAYER INDEX</p><h2 id="directory-title">選手を探す</h2><p>名前・ローマ字で検索できます。</p><label class="search-label" for="player-search">選手名</label><div class="search-box"><svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"></circle><path d="m15.5 15.5 5 5"></path></svg><input id="player-search" type="search" placeholder="例：酒井 春海" value="${h(filters.query)}" autocomplete="off"></div><fieldset><legend>カテゴリー</legend><div class="segments">${[
      ["", "すべて"],
      ["men", "男子"],
      ["women", "女子"],
    ]
      .map(
        ([value, label]) =>
          `<button data-gender="${value}" aria-pressed="${filters.gender === value}">${label}</button>`,
      )
      .join(
        "",
      )}</div></fieldset><label class="check"><input id="upcoming-only" type="checkbox" ${filters.upcoming ? "checked" : ""}>出場予定のある選手</label><label class="check"><input id="favorites-only" type="checkbox" ${filters.favorites ? "checked" : ""}>お気に入りだけ</label><div class="filter-note"><span aria-hidden="true">☆</span><p>気になる選手を保存。<br>お気に入りはこのブラウザに残ります。</p></div></aside><div class="directory-content"><div class="list-toolbar"><p id="result-count" role="status" aria-live="polite"></p><span>選手名 / 次の出場大会</span></div><div id="player-list"></div></div></section>`;
  document.querySelector("#player-search").addEventListener("input", (e) => {
    filters.query = e.target.value;
    renderPlayers();
  });
  document.querySelector("#upcoming-only").addEventListener("change", (e) => {
    filters.upcoming = e.target.checked;
    renderPlayers();
  });
  document.querySelector("#favorites-only").addEventListener("change", (e) => {
    filters.favorites = e.target.checked;
    renderPlayers();
  });
  document.querySelectorAll("[data-gender]").forEach((b) =>
    b.addEventListener("click", () => {
      filters.gender = b.dataset.gender;
      document
        .querySelectorAll("[data-gender]")
        .forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      renderPlayers();
    }),
  );
  renderPlayers();
}

function renderPlayers() {
  const players = filterPlayers(data, { ...filters, saved });
  document.querySelector("#result-count").innerHTML =
    `<strong>${players.length}</strong> 選手`;
  document.querySelector("#player-list").innerHTML = players.length
    ? players
        .map((p) => {
          const plans = appearances(data, p.id).filter(
            (a) => isUpcoming(a.event) && a.entry.status === "entered",
          );
          const next = plans[0];
          return `<article class="player-row"><a href="#player/${p.id}" class="player-link">${portrait(p)}<div class="player-identity"><span class="small-label">${genderName(p.gender)}</span><h3>${h(p.name)}</h3><p>${h(p.roman || "BEACH VOLLEYBALL")}</p></div><div class="player-next">${next ? `<span class="small-label">次の出場予定</span><strong>${range(next.event)}</strong><span>${h(next.event.name)}</span>` : '<span class="muted">公開された出場予定はありません</span>'}</div><span class="row-arrow" aria-hidden="true">↗</span></a>${favorite(p)}</article>`;
        })
        .join("")
    : empty(
        filters.favorites
          ? "条件に合うお気に入りの選手がいません"
          : "条件に合う選手が見つかりません",
        '<p>名前や絞り込み条件を変えてみてください。</p><button class="button" id="reset-filters">絞り込みをリセット</button>',
      );
  document.querySelector("#reset-filters")?.addEventListener("click", () => {
    Object.assign(filters, {
      query: "",
      gender: "",
      upcoming: false,
      favorites: false,
    });
    home();
  });
}

function appearanceCard({ event, entry }, playerId) {
  const partner = data.players.find(
    (p) => p.id === entry.playerIds.find((id) => id !== playerId),
  );
  return `<article class="appearance"><div class="date-block"><span>${event.startDate?.slice(0, 4) || "日程"}</span><strong>${range(event)}</strong><span>${event.cancelled ? "開催中止" : isUpcoming(event) ? "開催予定" : "終了"}</span></div><div class="appearance-body"><div class="badge-line"><span class="small-label">${h(event.category)}</span>${badge(entry, event)}</div><h3><a href="#event/${event.id}">${h(event.name)}</a></h3><p>${h(event.venue || "会場は公式情報をご確認ください")}</p><p class="partner">ペア <a href="#player/${partner.id}">${h(partner.name)} ↗</a></p><div class="source-links">${external(event.sourceUrl, "公式の大会情報")}${external(entry.sourceUrl, entry.status === "completed" ? "公式の結果 PDF" : /\.pdf(?:#|\?|$)/i.test(entry.sourceUrl) ? "掲載名簿 PDF" : "公式の出場メンバー")}</div></div></article>`;
}

function playerPage(id) {
  const p = data.players.find((p) => p.id === id);
  if (!p) return notFound();
  const all = appearances(data, id);
  const plans = all.filter((a) => isUpcoming(a.event));
  const results = all
    .filter((a) => a.entry.status === "completed")
    .sort((a, b) => b.event.endDate.localeCompare(a.event.endDate));
  const ended = all.filter(
    (a) => !isUpcoming(a.event) && a.entry.status !== "completed",
  );
  document.title = `${p.name}の出場予定・大会結果 | BEACH NOTE`;
  main.innerHTML = `<a class="back-link" href="#players">← 選手一覧へ</a><section class="profile-heading"><div class="profile-identity">${portrait(p, true)}<div><p class="eyebrow">${genderName(p.gender)} / PLAYER NOTE</p><h1>${h(p.name)}</h1><p class="roman">${h(p.roman)}</p></div></div><div class="profile-actions">${favorite(p)}${p.profileUrl ? external(p.profileUrl, "公式プロフィール") : ""}</div></section><div class="profile-layout"><section><div class="section-heading"><h2>これからの出場予定</h2><span>${plans.length} 大会</span></div>${plans.length ? plans.map((a) => appearanceCard(a, id)).join("") : empty("公開された出場予定はありません", '<p>名簿公開前の大会や未収録の大会に出場する場合もあります。</p><a class="button" href="#events">大会カレンダーへ</a>')}<section class="past-results" aria-labelledby="past-results-heading"><div class="section-heading"><h2 id="past-results-heading">過去の大会結果</h2><span>${results.length} 大会</span></div><p class="history-note">2026年BVT1の6大会を収録（立川立飛は女子のみ）。公式の最終順位と当時のペアを掲載しています。記録がない大会も、欠場を意味するものではありません。</p>${results.length ? results.map((a) => appearanceCard(a, id)).join("") : empty("収録済みの結果はありません", "<p>今後、確認できた公式結果を追加していきます。</p>")}</section>${ended.length ? `<details class="past"><summary>取得済みの終了・中止大会（${ended.length}件）</summary>${ended.map((a) => appearanceCard(a, id)).join("")}</details>` : ""}</section><aside class="note-panel"><p class="eyebrow">ABOUT THIS NOTE</p><h2>公式発表を、<br>そのまま手がかりに。</h2><p>掲載名簿に名前のある大会をまとめています。出場変更や当日の予定は公式情報でご確認ください。</p><p>補欠は「出場予定」と分けて表示しています。</p><p class="small-label">最終取得<br>${stamp(data.checkedAt || data.generatedAt)}</p></aside></div>`;
}

function eventsPage() {
  main.innerHTML = `<section class="page-heading"><p class="eyebrow">TOURNAMENT CALENDAR / ${data.year}</p><h1>次の週末は、どの海へ。</h1><p>開催日と会場から、大会を探す。</p></section>${freshness()}<div class="event-filters"><label>大会名・会場<input id="event-search" type="search" placeholder="例：相馬、神奈川" value="${h(eventFilters.query)}"></label><label>カテゴリー<select id="event-category"><option value="">すべて</option>${[
    ...new Set(data.events.map((e) => e.category)),
  ]
    .sort()
    .map(
      (c) =>
        `<option ${eventFilters.category === c ? "selected" : ""}>${h(c)}</option>`,
    )
    .join(
      "",
    )}</select></label><label>表示期間<select id="event-period"><option value="upcoming" ${eventFilters.period === "upcoming" ? "selected" : ""}>これからの大会</option><option value="past" ${eventFilters.period === "past" ? "selected" : ""}>終了した大会</option><option value="all" ${eventFilters.period === "all" ? "selected" : ""}>取得済みのすべて</option></select></label></div><div id="events-list"></div>`;
  for (const [id, field] of [
    ["event-search", "query"],
    ["event-category", "category"],
    ["event-period", "period"],
  ])
    document.getElementById(id).addEventListener("input", (e) => {
      eventFilters[field] = e.target.value;
      renderEvents();
    });
  renderEvents();
}

function renderEvents() {
  const events = filterEvents(data, eventFilters);
  let month = "";
  document.querySelector("#events-list").innerHTML =
    `<p class="calendar-count" role="status">${events.length} 大会</p>` +
    (events.length
      ? events
          .map((e) => {
            const m = e.startDate?.slice(0, 7) || "日程未定";
            const heading =
              month !== m
                ? `<h2 class="month-heading"><strong>${e.startDate ? Number(m.slice(5)) : "—"}</strong><span>${e.startDate ? `${m.slice(0, 4)} / ${Number(m.slice(5))}月` : m}</span></h2>`
                : "";
            month = m;
            return `${heading}<a class="event-row" href="#event/${e.id}"><span class="event-date">${range(e)}</span><div><span class="small-label">${h(e.category)}</span><h3>${h(e.name)}</h3><p>${h(e.venue)}</p></div><span class="badge ${e.entries.length && !e.cancelled ? "" : "sand"}">${e.cancelled ? "開催中止" : e.entries.length ? "選手情報あり" : "日程掲載"}</span><span aria-hidden="true">↗</span></a>`;
          })
          .join("")
      : empty(
          "条件に合う大会がありません",
          "<p>大会名・会場・表示期間を変更してください。</p>",
        ));
}

function eventPage(id) {
  const e = data.events.find((e) => e.id === id);
  if (!e) return notFound();
  document.title = `${e.name} | BEACH NOTE`;
  const status =
    e.entryStatus === "review"
      ? "参加名簿の一部は確認中です。掲載のない選手については公式資料をご覧ください。"
      : "取得時点で出場選手の発表を確認できていません。公式ページで最新情報をご確認ください。";
  main.innerHTML = `<a class="back-link" href="#events">← 大会カレンダーへ</a><section class="event-heading"><p class="eyebrow">${h(e.category)} / TOURNAMENT NOTE</p><h1>${h(e.name)}</h1><div class="event-meta"><strong>${range(e)}</strong><p>${h(e.venue)}</p>${e.cancelled ? '<span class="badge sand">開催中止</span>' : ""}</div>${external(e.sourceUrl, "公式の大会情報を見る", "button primary")}</section><div class="profile-layout"><section><div class="section-heading"><h2>${e.entries.some((entry) => entry.status === "completed") ? "大会結果・ペア" : "出場選手・ペア"}</h2><span>${e.entries.length} ペア</span></div>${e.resultCoverage ? `<p class="notice">${h(e.resultCoverage)}</p>` : ""}${e.entryStatus === "review" || !e.entries.length ? `<p class="notice">${status}</p>` : ""}${[
    "men",
    "women",
  ]
    .map((gender) => {
      const entries = e.entries.filter((x) => x.gender === gender);
      return entries.length
        ? `<h3 class="gender-heading">${genderName(gender)} <span>${entries.length} ペア</span></h3><div class="teams">${entries.map((entry) => `<div class="team"><div>${entry.playerIds.map((id) => `<a href="#player/${id}">${h(data.players.find((p) => p.id === id).name)}</a>`).join('<span class="pair-divider"> / </span>')}</div>${badge(entry, e)}${external(entry.sourceUrl, entry.status === "completed" ? "結果 PDF" : "名簿")}</div>`).join("")}</div>`
        : "";
    })
    .join(
      "",
    )}</section><aside class="documents"><p class="eyebrow">OFFICIAL DOCUMENTS</p><h2>公式資料</h2><p>時刻や組み合わせは、公式の発表資料へ。</p>${(e.relatedSources || []).map((d) => external(d.url, d.label, "document-link")).join("")}${e.documents.length ? e.documents.map((d) => external(d.url, d.label, "document-link")).join("") : '<p class="muted">添付資料はまだ収録されていません。</p>'}<p class="small-label">最終取得<br>${stamp(e.checkedAt || data.checkedAt || data.generatedAt)}</p></aside></div>`;
}

function aboutPage() {
  main.innerHTML = `<article class="about"><p class="eyebrow">ABOUT BEACH NOTE</p><h1>探す時間を、<br>応援する時間に。</h1><p class="lead">ビーチバレーの選手が、いつ、どの大会に出るのか。公式に公開された情報を、選手から辿れるようにまとめた非公式の観戦ガイドです。</p><h2>掲載している情報</h2><p>${h(data.coverage.description)}</p><dl class="coverage"><div><dt>基準日</dt><dd>${h(data.asOf || todayJst())}</dd></div><div><dt>最終取得</dt><dd>${stamp(data.checkedAt || data.generatedAt)}</dd></div><div><dt>収録内容</dt><dd>${data.players.length} 選手 / ${data.events.length} 大会</dd></div><div><dt>確認した資料</dt><dd>${data.coverage.pagesChecked} 記事 / ${data.coverage.pdfsChecked} PDF</dd></div></dl><h2>予定が見つからないとき</h2><p>名簿が未発表の大会、掲載形式の確認が必要な資料は、選手の予定に反映されていない場合があります。「予定なし」は欠場を意味しません。補欠は区別して掲載し、勝ち上がりや出場を予測することはありません。</p><h2>情報の更新について</h2><p>公式情報を確認した時点の内容を掲載しています。リアルタイム更新ではありません。各大会・名簿へのリンクから、最新の変更をご確認ください。過去の大会結果は2026年BVT1の6大会（立川立飛は女子のみ）から収録しています。公式に明記された最終順位だけを掲載し、予選順位や対戦表から順位を推測しません。</p><h2>参照元</h2><div class="source-links">${external("https://www.jbv.jp/", "日本ビーチバレーボール連盟（JBV）")}${external("https://www.jva.or.jp/beach_domestic/2026/", "日本バレーボール協会（JVA）")}</div><h2>お気に入りについて</h2><p>お気に入りはお使いのブラウザ内に保存します。アカウント登録は不要です。別の端末との同期はありません。</p><p class="notice">当サイトはJBV・JVAによる公式サイトではありません。選手の写真や公式記事の全文は転載せず、出典へのリンクを掲載しています。</p></article>`;
}

function notFound() {
  main.innerHTML = empty(
    "このページは見つかりません",
    '<a class="button" href="#players">選手一覧へ戻る</a>',
  );
}
function route(focus = true) {
  const [view, id] = (location.hash.slice(1) || "players").split("/");
  if (view === "main") {
    main.focus();
    return;
  }
  document.title = "BEACH NOTE — 選手から探す、ビーチバレー";
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const active =
      a.dataset.nav ===
      (view === "player" ? "players" : view === "event" ? "events" : view);
    if (active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  (
    ({
      players: home,
      player: () => playerPage(id),
      events: eventsPage,
      event: () => eventPage(id),
      about: aboutPage,
    })[view] || notFound
  )();
  if (focus) {
    main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
}

main.addEventListener("click", (e) => {
  const button = e.target.closest("[data-save]");
  if (!button) return;
  const id = button.dataset.save;
  saved = saved.includes(id) ? saved.filter((x) => x !== id) : [...saved, id];
  try {
    localStorage.setItem("beach-note:favorites", JSON.stringify(saved));
  } catch {
    /* Remain useful for the current session. */
  }
  button.classList.toggle("is-saved", saved.includes(id));
  button.textContent = saved.includes(id) ? "★" : "☆";
  button.setAttribute("aria-pressed", String(saved.includes(id)));
  button.setAttribute(
    "aria-label",
    `${data.players.find((p) => p.id === id).name}をお気に入り${saved.includes(id) ? "から削除" : "に追加"}`,
  );
  if (filters.favorites && document.querySelector("#player-list"))
    renderPlayers();
});
main.addEventListener(
  "error",
  (event) => {
    if (event.target.matches("[data-profile-photo]")) event.target.remove();
  },
  true,
);

try {
  const response = await fetch(new URL("./data/beach.json", import.meta.url), {
    cache: "no-cache",
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  data = await response.json();
  if (
    data.schemaVersion !== 1 ||
    !Array.isArray(data.players) ||
    !Array.isArray(data.events)
  )
    throw new Error("Invalid data");
  window.addEventListener("hashchange", () => route());
  route(false);
} catch (error) {
  console.error(error);
  main.innerHTML = `<div class="empty" role="alert"><h1>データを読み込めませんでした</h1><p>通信状態を確認して、ページを再読み込みしてください。</p><button class="button" id="retry">再読み込み</button>${external("https://www.jbv.jp/", "JBV公式サイトへ")}</div>`;
  document
    .querySelector("#retry")
    .addEventListener("click", () => location.reload());
}
