#!/usr/bin/env python3
"""Fetch official JBV information locally; publish only validated, attributable facts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from scripts.history import collect_history
from scripts.parsers import normalize, parse_article, parse_profiles, parse_roster, parse_calendar, parse_jva_calendar, parse_jva_teams, safe_url, soup_body, stable_id

ROOT = Path(__file__).resolve().parents[1]
UA = 'BeachNote/1.0 (+https://github.com/misoclub-apps/mc-beach-volleyball; local periodic index)'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


class Fetcher:
    def __init__(self, interval, offline=False, allowed_hosts=None):
        self.cache = ROOT / '.cache/http'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.interval, self.offline, self.last = interval, offline, 0
        self.session = requests.Session()
        self.session.headers['User-Agent'] = UA
        self.session.headers['Accept-Encoding'] = 'gzip, deflate'
        self.allowed_hosts = set(allowed_hosts or ['www.jbv.jp', 'jbv.jp'])
        self.records, self.robots, self.warnings = {}, {}, []

    def get(self, url, robots=False):
        parts = urlparse(url)
        if parts.scheme != 'https' or parts.hostname not in self.allowed_hosts:
            raise ValueError(f'取得対象外のURL: {url}')
        if not robots and parts.hostname in self.robots and not self.robots[parts.hostname].can_fetch(UA, url):
            raise ValueError(f'robots.txtで取得禁止: {url}')
        key = hashlib.sha256(url.encode()).hexdigest()
        path, meta_path = self.cache / key, self.cache / (key + '.json')
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if self.offline:
            if not path.exists():
                raise ValueError(f'キャッシュなし: {url}')
            self.records[url] = meta
            return path.read_bytes()
        headers = {}
        if path.exists():
            for field, header in [('etag', 'If-None-Match'), ('lastModified', 'If-Modified-Since')]:
                if meta.get(field):
                    headers[header] = meta[field]
        time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        # Never follow a redirect to an unconfigured external/private host.
        response = self.session.get(url, headers=headers, timeout=(10, 40), allow_redirects=False, stream=True)
        try:
            if response.status_code == 304 and path.exists():
                data = path.read_bytes()
            else:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(f'未対応HTTP応答 {response.status_code}: {url}')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 30 * 1024 * 1024:
                        raise ValueError('ファイルが30MBを超えています')
                    chunks.append(chunk)
                data = b''.join(chunks)
                if urlparse(url).path.lower().endswith('.pdf') and not data.startswith(b'%PDF'):
                    raise ValueError('PDFではない応答です')
                path.write_bytes(data)
            meta = {'url': url, 'checkedAt': now(), 'sha256': hashlib.sha256(data).hexdigest(),
                    'etag': response.headers.get('ETag', meta.get('etag')),
                    'lastModified': response.headers.get('Last-Modified', meta.get('lastModified'))}
            write_json(meta_path, meta)
            self.records[url] = meta
            return data
        finally:
            response.close()

    def check_robots(self):
        if self.offline:
            return
        for host in sorted(self.allowed_hosts - {'jbv.jp'}):
            url = f'https://{host}/robots.txt'
            try:
                data = self.get(url, robots=True)
                rp = RobotFileParser(url)
                rp.parse(data.decode('utf-8', errors='replace').splitlines())
                self.robots[host] = rp
                self.interval = max(self.interval, rp.crawl_delay(UA) or rp.crawl_delay('*') or 0)
            except requests.HTTPError as error:
                if error.response.status_code in (404, 410):
                    continue
                # A server-side robots error is recorded, not interpreted as permission.
                self.warnings.append(f'robots.txt取得不可 (HTTP {error.response.status_code})。低頻度・公開ページのみ取得。運用条件は別途確認してください。')


def discover(fetcher, config, issues):
    pages, profiles, calendar = {}, [], []
    for url in config['seeds']:
        try:
            html = fetcher.get(url)
            soup, body = soup_body(html)
            if '/players/' in url:
                profiles += parse_profiles(html, url)
            if '/convention/' in url or '/convention-jva/' in url:
                calendar += parse_calendar(html, url, config['year'])
            if '/beach_international/' in url:
                calendar += parse_jva_calendar(html, url, config['year'])
            for a in soup.select('a[href]'):
                link = safe_url(url, a['href'])
                if link and re.match(r'https://www\.jbv\.jp/(news|schedule)/entry-\d+\.html$', link):
                    pages[link] = a.get_text(' ', strip=True)
        except Exception as error:
            issues.append({'url': url, 'kind': 'discovery', 'message': str(error)})
    for url in config.get('extraPages', []):
        pages[url] = '追加対象'
    return pages, profiles, calendar


def compile_players(events, profiles, aliases):
    aliases = {normalize(k): normalize(v) for k, v in aliases.items()}
    def key(name, gender):
        norm = normalize(name)
        return gender + ':' + aliases.get(norm, norm)
    players = {}
    def player(name, gender, profile=None):
        canonical = key(name, gender)
        pid = stable_id('p-', canonical)
        if pid not in players:
            players[pid] = {'id': pid, 'name': name, 'gender': gender, 'aliases': [], 'roman': '',
                            'profileUrl': None, 'imageUrl': None}
        p = players[pid]
        if name not in p['aliases']:
            p['aliases'].append(name)
        if profile:
            p.update({k: profile[k] for k in ('name', 'roman', 'profileUrl', 'imageUrl')})
        return pid
    for p in profiles:
        player(p['name'], p['gender'], p)
    for event in events:
        for entry in event['entries']:
            entry['playerIds'] = [player(name, entry['gender']) for name in entry.pop('names')]
    return sorted(players.values(), key=lambda p: p['name'])


def validate(dataset):
    players = {p['id'] for p in dataset['players']}
    if len(players) != len(dataset['players']):
        raise ValueError('選手IDが重複しています')
    for e in dataset['events']:
        if e['startDate'] and e['endDate'] < e['startDate']:
            raise ValueError(f'日付の前後が不正: {e["id"]}')
        members = set()
        for entry in e['entries']:
            if len(entry['playerIds']) != 2 or len(set(entry['playerIds'])) != 2:
                raise ValueError(f'ペア情報が不正: {e["id"]}')
            for pid in entry['playerIds']:
                if pid not in players or pid in members:
                    raise ValueError(f'名簿の重複または不明な選手: {e["id"]} / {pid}')
                members.add(pid)
            if entry['status'] not in ('entered', 'reserve', 'withdrawn', 'completed'):
                raise ValueError('不明な参加状態')
            if entry['status'] == 'completed' and (not isinstance(entry.get('rank'), int) or entry['rank'] < 1 or not entry.get('resultLabel')):
                raise ValueError('最終順位が不正です')
            if not entry.get('sourceUrl'):
                raise ValueError('出典のない参加情報')


def run(args):
    config = json.loads((ROOT / 'config/sources.json').read_text())
    overrides = json.loads((ROOT / 'config/overrides.json').read_text())
    issues, events = [], []
    if len({h.removeprefix('www.') for h in config['allowedHosts']}) > config['maxDomains']:
        raise ValueError('取得対象が10ドメインを超えています')
    as_of = args.as_of or datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
    fetcher = Fetcher(config['requestIntervalSeconds'], args.offline, config['allowedHosts'])
    fetcher.check_robots()
    pages, profiles, calendar = discover(fetcher, config, issues)
    if not profiles or not pages:
        raise ValueError('公式サイトの取得に失敗しました。公開データは変更しません。')
    ignored = set(overrides.get('ignoredPages', []))
    candidates = [(u, t) for u, t in pages.items() if u not in ignored]
    limit = args.limit or config['maxPages']
    pdf_count = 0
    skipped = []
    for index, (url, title) in enumerate(candidates[:limit], 1):
        print(f'[{index}/{min(len(candidates), limit)}] {title[:65]}', flush=True)
        try:
            event = parse_article(fetcher.get(url), url, config['year'])
            if not event:
                skipped.append({'url': url, 'title': title, 'reason': '対応する大会日程の記載なし'})
                continue
            event['checkedAt'] = fetcher.records[url]['checkedAt']
            event.update(overrides.get('events', {}).get(event['id'], {}))
            if event['endDate'] and event['endDate'] < as_of:
                skipped.append({'url': url, 'title': title, 'reason': '過去大会（今回の対象外）'})
                continue
            if not event['startDate']:
                issues.append({'url': url, 'kind': 'date', 'message': '開催日の解析を確認してください'})
            for gender in ('men', 'women'):
                docs = [d for d in event['documents'] if d['kind'] in ('entry', 'seed') and d['gender'] == gender]
                # Latest file date takes priority; seed wins on equal date. Never fall back
                # to an older roster after the current roster failed validation.
                def doc_order(d):
                    dates = re.findall(r'20\d{6}', d['url'])
                    return (max(dates) if dates else '', d['kind'] == 'seed')
                docs.sort(key=doc_order, reverse=True)
                if not docs:
                    continue
                doc = docs[0]
                if pdf_count >= config['maxPdfs']:
                    issues.append({'url': doc['url'], 'kind': 'limit', 'message': 'PDF取得上限。次回の上限を増やしてください'})
                    event['entryStatus'] = 'review'
                    continue
                pdf_count += 1
                try:
                    data = fetcher.get(doc['url'])
                    teams, problems = parse_roster(data, gender)
                    for message in problems:
                        issues.append({'url': doc['url'], 'eventId': event['id'], 'kind': 'roster', 'message': message})
                    if problems:
                        event['entryStatus'] = 'review'
                    for team in teams:
                        team['sourceUrl'] = doc['url'] + f'#page={team["page"]}'
                        team['checkedAt'] = fetcher.records[doc['url']]['checkedAt']
                        event['entries'].append(team)
                    doc['parsed'] = bool(teams)
                except Exception as error:
                    event['entryStatus'] = 'review'
                    issues.append({'url': doc['url'], 'eventId': event['id'], 'kind': 'fetch', 'message': str(error)})
            if event['id'] in overrides.get('entries', {}):
                event['entries'] = overrides['entries'][event['id']]
                event['entryStatus'] = 'manual'
            elif event['entries'] and event['entryStatus'] != 'review':
                event['entryStatus'] = 'published'
            events.append(event)
        except Exception as error:
            issues.append({'url': url, 'kind': 'article', 'message': str(error)})
    if len(candidates) > limit:
        issues.append({'kind': 'limit', 'message': f'{len(candidates)-limit}ページが取得上限で未処理'})
    for event in calendar:
        if event['endDate'] < as_of:
            continue
        def same_event(other):
            a, b = normalize(event['name']), normalize(other['name'])
            return other['startDate'] == event['startDate'] and (a in b or b in a or ('小浜' in other['name'] and '北信越' in event['name']))
        if not any(same_event(e) for e in events):
            event['checkedAt'] = fetcher.records[event.get('scheduleSourceUrl', event['sourceUrl'])]['checkedAt']
            event.update(overrides.get('events', {}).get(event['id'], {}))
            events.append(event)
    external_review = []
    for url in config.get('reviewPages', []):
        try:
            html = fetcher.get(url)
            soup, body = soup_body(html)
            external_review.append({'url': url, 'checkedAt': fetcher.records[url]['checkedAt'],
                                    'title': soup.title.get_text(strip=True) if soup.title else '',
                                    'text': body.get_text('\n', strip=True),
                                    'links': [{'label': a.get_text(' ', strip=True), 'url': safe_url(url, a['href'])} for a in body.select('a[href]')]})
        except Exception as error:
            issues.append({'url': url, 'kind': 'external', 'message': str(error)})
    write_json(ROOT / 'reports/external-review.json', external_review)
    for source in config.get('htmlRosters', []):
        event = next((e for e in events if e['sourceUrl'] == source['eventUrl']), None)
        if event is None:
            continue
        try:
            teams, problems = parse_jva_teams(fetcher.get(source['url']), profiles)
            for problem in problems:
                issues.append({'url': source['url'], 'eventId': event['id'], 'kind': 'roster', 'message': problem})
            for team in teams:
                team['sourceUrl'] = source['url']
                team['checkedAt'] = fetcher.records[source['url']]['checkedAt']
            event['entries'] = teams
            event['entryStatus'] = 'review' if problems else 'published' if teams else 'unpublished'
            event['documents'].append({'url': source['url'], 'label': '日本の出場メンバー（JVA）', 'kind': 'entry', 'gender': None})
        except Exception as error:
            issues.append({'url': source['url'], 'kind': 'external', 'message': str(error)})
    history, history_pdfs = collect_history(fetcher, config, as_of)
    events.extend(history)
    pdf_count += history_pdfs
    if pdf_count > config['maxPdfs']:
        raise ValueError('結果PDFを含む取得上限超過')
    players = compile_players(events, profiles, overrides.get('aliases', {}))
    dataset = {'schemaVersion': 1, 'generatedAt': now(), 'checkedAt': max(r['checkedAt'] for r in fetcher.records.values()), 'asOf': as_of, 'year': config['year'],
               'coverage': {'source': 'JBV・JVA・各大会主催者',
                            'description': 'JBVの年間予定・ニュース・公認大会とJVA国際大会予定から、取得時点で開催前または開催中の大会を収録。主催者サイトも確認し、大会別に公開された参加名簿を選手に紐付けています。未発表の出場予定は含みません。過去の結果は2026年BVT1の6大会を対象に、公式最終順位表から収録（立川立飛は女子のみ）。全大会・全試合を網羅するものではありません。',
                            'domains': sorted({urlparse(u).hostname for u in fetcher.records}),
                            'reviewedSources': [{'url': r['url'], 'title': r['title'], 'checkedAt': r['checkedAt']} for r in external_review],
                            'pagesDiscovered': len(candidates), 'pagesChecked': min(len(candidates), limit),
                            'pdfsChecked': pdf_count, 'reviewCount': len(issues), 'offline': args.offline,
                            'skippedCount': len(skipped)},
               'players': players, 'events': sorted(events, key=lambda e: (e['startDate'] or '9999', e['name'])),
               'issues': [{'eventId': i.get('eventId'), 'url': i.get('url'), 'kind': i['kind']} for i in issues]}
    validate(dataset)
    if not events or not any(e['entries'] for e in events):
        raise ValueError('有効な大会・出場データがありません。公開データは変更しません。')
    write_json(ROOT / 'reports/update.json', {'at': now(), 'issues': issues, 'skipped': skipped,
                                             'warnings': fetcher.warnings, 'sources': fetcher.records})
    # Hard fetch/discovery failures must not erase the last good snapshot.
    failures = [i for i in issues if i['kind'] in ('fetch', 'discovery', 'article', 'limit', 'external', 'date')]
    if failures:
        raise ValueError(f'{len(failures)}件の取得エラー。reports/update.json を確認してください。公開データは変更しません。')
    output = ROOT / 'public/data/beach.json'
    old = json.loads(output.read_text()) if output.exists() else None
    if old:
        old_events = {e['id'] for e in old['events']}
        new_events = {e['id'] for e in events}
        write_json(ROOT / 'reports/changes.json', {'added': sorted(new_events-old_events), 'removed': sorted(old_events-new_events),
                                                  'playersBefore': len(old['players']), 'playersAfter': len(players)})
        unexpectedly_missing = [e['id'] for e in old['events'] if e['id'] not in new_events
                                and (e['endDate'] or '9999') >= as_of
                                and e['id'] not in overrides.get('removedEvents', {})]
        if unexpectedly_missing:
            raise ValueError('未開催大会が消えています。掲載変更を確認し、必要なら overrides.removedEvents に理由を記録してください: ' + ', '.join(unexpectedly_missing))
    write_json(output, dataset)
    print(f'\n完了: {len(players)}選手 / {len(events)}大会 / {sum(len(e["entries"]) for e in events)}ペア / 要確認{len(issues)}件')
    for warning in fetcher.warnings:
        print('注意:', warning)
    print('公開データ: public/data/beach.json / 詳細: reports/update.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='保存した原本だけで再解析（ネットワーク不要）')
    parser.add_argument('--as-of', help='対象の基準日 YYYY-MM-DD（既定: 日本時間の今日）')
    parser.add_argument('--limit', type=int, help='調査用の最大記事数（超過時は公開データを変更しない）')
    args = parser.parse_args()
    lock = ROOT / '.cache/update.lock'
    lock.parent.mkdir(exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        sys.exit('更新処理が実行中です。異常終了の場合のみ .cache/update.lock を削除してください。')
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        run(args)
    except Exception as error:
        print(f'更新失敗: {error}', file=sys.stderr)
        sys.exit(1)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
