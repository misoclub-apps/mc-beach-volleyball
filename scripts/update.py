#!/usr/bin/env python3
"""Fetch official JBV information locally; publish only validated, attributable facts."""
import argparse
import copy
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
from scripts.parsers import discover_volleyball_world_japan_match_urls, normalize, parse_article, parse_profile_image, parse_profiles, parse_roster, parse_calendar, parse_jva_calendar, parse_jva_final_standings, parse_jva_teams, parse_volleyball_world_final_standings, parse_volleyball_world_match, parse_volleyball_world_teams, safe_url, soup_body, stable_id

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
    def __init__(self, interval, offline=False, allowed_hosts=None, max_retries=5):
        self.cache = ROOT / '.cache/http'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.interval, self.offline, self.last = interval, offline, 0
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers['User-Agent'] = UA
        self.session.headers['Accept-Encoding'] = 'gzip, deflate'
        self.allowed_hosts = set(allowed_hosts or ['www.jbv.jp', 'jbv.jp'])
        self.records, self.robots, self.warnings = {}, {}, []

    def cached(self, url):
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / key
        return path.read_bytes() if path.exists() else None

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
        for attempt in range(self.max_retries + 1):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            response = None
            try:
                # Never follow a redirect to an unconfigured external/private host.
                response = self.session.get(url, headers=headers, timeout=(10, 40),
                                            allow_redirects=False, stream=True)
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
                        raise requests.ConnectionError('PDFではない一時応答です')
                    path.write_bytes(data)
                meta = {'url': url, 'checkedAt': now(), 'sha256': hashlib.sha256(data).hexdigest(),
                        'etag': response.headers.get('ETag', meta.get('etag')),
                        'lastModified': response.headers.get('Last-Modified', meta.get('lastModified'))}
                write_json(meta_path, meta)
                self.records[url] = meta
                return data
            except requests.RequestException as error:
                status = getattr(getattr(error, 'response', None), 'status_code', None)
                retryable = status in (408, 429) or (status is not None and status >= 500) or status is None
                if not retryable or attempt >= self.max_retries:
                    raise
                retry_after = response.headers.get('Retry-After') if response is not None else None
                delay = min(int(retry_after), 60) if retry_after and retry_after.isdigit() else min(2 ** (attempt + 1), 16)
                print(f'[retry {attempt + 1}/{self.max_retries}] {status or type(error).__name__}: {url} ({delay}秒後)', flush=True)
                time.sleep(delay)
            finally:
                if response is not None:
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
    for index, profile in enumerate(profiles, 1):
        print(f'[profile {index}/{len(profiles)}] {profile["name"]}', flush=True)
        try:
            portrait = parse_profile_image(fetcher.get(profile['profileUrl']), profile['profileUrl'], profile['name'])
            if portrait:
                profile['imageUrl'] = portrait
            else:
                issues.append({'url': profile['profileUrl'], 'kind': 'profile-image',
                               'message': '個別プロフィールの本人画像を確認できないため一覧画像を使用'})
        except Exception as error:
            cached = fetcher.cached(profile['profileUrl'])
            portrait = parse_profile_image(cached, profile['profileUrl'], profile['name']) if cached else None
            if portrait:
                profile['imageUrl'] = portrait
                issues.append({'url': profile['profileUrl'], 'kind': 'profile-image',
                               'message': f'個別ページの再取得失敗。保存済みページの画像を維持: {error}'})
            else:
                issues.append({'url': profile['profileUrl'], 'kind': 'profile-image', 'message': str(error)})
    for url in config.get('extraPages', []):
        pages[url] = '追加対象'
    return pages, profiles, calendar


def compile_players(events, profiles, aliases):
    display_aliases = {normalize(k): v.strip() for k, v in aliases.items()}
    aliases = {key: normalize(value) for key, value in display_aliases.items()}
    def key(name, gender):
        norm = normalize(name)
        return gender + ':' + aliases.get(norm, norm)
    players = {}
    def player(name, gender, profile=None):
        canonical = key(name, gender)
        pid = stable_id('p-', canonical)
        display_name = display_aliases.get(normalize(name), name)
        if pid not in players:
            players[pid] = {'id': pid, 'name': display_name, 'gender': gender, 'aliases': [], 'roman': '',
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
            if len(entry['playerIds']) not in (1, 2) or len(set(entry['playerIds'])) != len(entry['playerIds']):
                raise ValueError(f'ペア情報が不正: {e["id"]}')
            for pid in entry['playerIds']:
                if pid not in players or pid in members:
                    raise ValueError(f'名簿の重複または不明な選手: {e["id"]} / {pid}')
                members.add(pid)
            if entry['status'] not in ('entered', 'reserve', 'withdrawn', 'completed', 'resultPending'):
                raise ValueError('不明な参加状態')
            if entry['status'] == 'completed' and (not isinstance(entry.get('rank'), int) or entry['rank'] < 1 or not entry.get('resultLabel')):
                raise ValueError('最終順位が不正です')
            if not entry.get('sourceUrl'):
                raise ValueError('出典のない参加情報')
        for match in e.get('matches', []):
            if match['home']['countryCode'] != 'JPN' and match['away']['countryCode'] != 'JPN':
                raise ValueError('日本が関係しない国際試合です')
            if not match.get('sourceUrl') or not match.get('id'):
                raise ValueError('出典のない国際試合です')


def apply_event_overrides(event, overrides):
    """Preserve public event IDs when an official calendar adds a detail URL."""
    preserved_id = overrides.get('eventIds', {}).get(event['sourceUrl'])
    if preserved_id:
        event['id'] = preserved_id
    event.update(overrides.get('events', {}).get(event['id'], {}))


def merge_volleyball_world_entries(event, official_entries, aliases):
    """Replace international entries while preserving known Japanese display names."""
    canonical = {normalize(k): normalize(v) for k, v in aliases.items()}

    def team_key(entry):
        return (entry['gender'], tuple(sorted(canonical.get(normalize(n), normalize(n)) for n in entry['names'])))

    existing = {team_key(entry): entry for entry in event['entries']}
    merged = []
    for official in official_entries:
        current = existing.get(team_key(official))
        if current:
            current.update({key: value for key, value in official.items() if key != 'names'})
            merged.append(current)
        else:
            official['names'] = [canonical.get(normalize(name), name.strip()) for name in official['names']]
            merged.append(official)
    event['entries'] = merged


def collect_volleyball_world(events, fetcher, config, profiles, aliases, issues, as_of):
    """Collect JPN teams and explicitly configured official match pages only."""
    sources = config.get('volleyballWorldEvents', [])
    all_aliases = dict(aliases)
    jva_rosters = {}
    for source in sources:
        try:
            teams, problems = parse_jva_teams(fetcher.get(source['eventUrl']), profiles)
            for team in teams:
                for english, japanese in zip(team.pop('englishNames', []), team['names']):
                    all_aliases.setdefault(english, japanese)
            jva_rosters[source['eventUrl']] = teams
        except Exception as error:
            issues.append({'url': source['eventUrl'], 'kind': 'external', 'message': str(error)})

    for source in sources:
        event = next((item for item in events if item['sourceUrl'] == source['eventUrl']), None)
        if event is None:
            issues.append({'url': source['url'], 'kind': 'external',
                           'message': '対応するJVA大会を確認できません'})
            continue
        jva_teams = jva_rosters.get(source['eventUrl'], [])
        if jva_teams:
            event['entries'] = jva_teams
            event['entryStatus'] = 'published'
        official_entries = []
        team_pages_complete = True
        for gender in source.get('genders', ('men', 'women')):
            for stage in ('main-draw', 'qualification', 'reserve'):
                url = f'{source["url"].rstrip("/")}/teams/{gender}/{stage}'
                try:
                    official_entries.extend(parse_volleyball_world_teams(
                        fetcher.get(url), gender, stage, url))
                except Exception as error:
                    team_pages_complete = False
                    issues.append({'url': url, 'eventId': event['id'], 'kind': 'external',
                                   'message': str(error)})
        official_entries = list({entry['externalTeamId']: entry for entry in reversed(official_entries)}.values())
        if team_pages_complete:
            merge_volleyball_world_entries(event, official_entries, all_aliases)
        if event.get('endDate') and event['endDate'] < as_of and team_pages_complete:
            standings, standings_complete = [], True
            for gender in source.get('genders', ('men', 'women')):
                url = f'{source["url"].rstrip("/")}/standings/{gender}/'
                try:
                    gender_results = parse_volleyball_world_final_standings(fetcher.get(url), gender, url)
                    standings.extend(gender_results)
                except Exception as error:
                    standings_complete = False
                    issues.append({'url': url, 'eventId': event['id'], 'kind': 'result',
                                   'message': str(error)})
            if standings_complete and standings:
                by_team = {result['externalTeamId']: result for result in standings}
                event['entries'] = [entry for entry in event['entries'] if entry.get('externalTeamId') in by_team]
                for entry in event['entries']:
                    result = by_team[entry['externalTeamId']]
                    entry.update({'status': 'completed', 'rank': result['rank'],
                                  'resultLabel': f'{result["rank"]}位', 'sourceUrl': result['sourceUrl']})
                event['entryStatus'] = 'published'
                event['resultCoverage'] = 'Volleyball World公式最終順位表で確認した日本ペアのみ掲載しています。'
            elif standings_complete:
                for entry in event['entries']:
                    entry['status'] = 'resultPending'
                event['entryStatus'] = 'resultPending'
                event['resultCoverage'] = '公式最終順位表に日本ペアの順位を確認できないため、公開済み名簿を保持しています。'
        event['matches'] = []
        match_urls = list(source.get('matchUrls', []))
        try:
            match_urls.extend(discover_volleyball_world_japan_match_urls(
                fetcher.get(source['url']), source['url']))
        except Exception as error:
            issues.append({'url': source['url'], 'eventId': event['id'], 'kind': 'discovery',
                           'message': str(error)})
        for url in dict.fromkeys(match_urls):
            try:
                event['matches'].append(parse_volleyball_world_match(fetcher.get(url), url))
            except Exception as error:
                issues.append({'url': url, 'eventId': event['id'], 'kind': 'external',
                               'message': str(error)})
        event.setdefault('relatedSources', []).append(
            {'url': source['url'], 'label': 'Volleyball World 公式大会ページ'})
        checked_urls = [entry['sourceUrl'] for entry in official_entries]
        if checked_urls:
            event['checkedAt'] = max(fetcher.records[url]['checkedAt'] for url in checked_urls)


def retain_unresolved_events(events, previous_events, as_of, previous_players=()):
    """Keep published player links after an event ends until final results exist."""
    existing_ids = {event['id'] for event in events}
    existing_urls = {event['sourceUrl'] for event in events}
    previous_names = {player['id']: player['name'] for player in previous_players}
    retained = 0
    for previous in previous_events:
        if previous['id'] in existing_ids or previous['sourceUrl'] in existing_urls:
            continue
        if not previous.get('entries') or not previous.get('endDate') or previous['endDate'] >= as_of:
            continue
        event = copy.deepcopy(previous)
        for entry in event['entries']:
            if 'names' not in entry and entry.get('playerIds'):
                try:
                    entry['names'] = [previous_names[player_id] for player_id in entry['playerIds']]
                except KeyError as error:
                    raise ValueError(f'保持する過去大会の選手名を復元できません: {event["id"]} / {error.args[0]}') from error
                entry.pop('playerIds', None)
            if entry['status'] == 'entered':
                entry['status'] = 'resultPending'
        event['entryStatus'] = 'resultPending'
        event['resultCoverage'] = '公式最終結果を確認中です。公開済みの参加名簿を保持しています。'
        events.append(event)
        existing_ids.add(event['id'])
        existing_urls.add(event['sourceUrl'])
        retained += 1
    return retained


def run(args):
    config = json.loads((ROOT / 'config/sources.json').read_text())
    overrides = json.loads((ROOT / 'config/overrides.json').read_text())
    issues, events = [], []
    if len({h.removeprefix('www.') for h in config['allowedHosts']}) > config['maxDomains']:
        raise ValueError('取得対象が10ドメインを超えています')
    as_of = args.as_of or datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
    output = ROOT / 'public/data/beach.json'
    old = json.loads(output.read_text()) if output.exists() else None
    old_by_url = {event['sourceUrl']: event for event in old['events']} if old else {}
    history_urls = {
        source['url'].split('#', 1)[0]
        for source in config.get('history', {}).get('directEvents', [])
    }
    retained_past_urls = (
        set(config.get('retainPastEvents', []))
        | {url for url in old_by_url if url.split('#', 1)[0] not in history_urls}
    )
    fetcher = Fetcher(config['requestIntervalSeconds'], args.offline, config['allowedHosts'],
                      config.get('maxRetries', 5))
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
            apply_event_overrides(event, overrides)
            is_past = bool(event['endDate'] and event['endDate'] < as_of)
            if is_past and url not in retained_past_urls:
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
            if is_past:
                previous = old_by_url.get(url)
                current_genders = {entry['gender'] for entry in event['entries']}
                if previous:
                    event['entries'].extend(
                        copy.deepcopy(entry) for entry in previous['entries']
                        if entry['gender'] not in current_genders
                    )
                for entry in event['entries']:
                    if entry['status'] == 'entered':
                        entry['status'] = 'resultPending'
                event['entryStatus'] = 'resultPending'
                event['resultCoverage'] = '公式最終結果を確認中です。公開済みの参加名簿を保持しています。'
            events.append(event)
        except Exception as error:
            issues.append({'url': url, 'kind': 'article', 'message': str(error)})
    if len(candidates) > limit:
        issues.append({'kind': 'limit', 'message': f'{len(candidates)-limit}ページが取得上限で未処理'})
    international_urls = (
        {source['eventUrl'] for source in config.get('volleyballWorldEvents', [])}
        | {source['eventUrl'] for source in config.get('htmlResults', [])}
    )
    for event in calendar:
        if event['endDate'] < as_of and event['sourceUrl'] not in international_urls:
            continue
        def same_event(other):
            a, b = normalize(event['name']), normalize(other['name'])
            return other['startDate'] == event['startDate'] and (a in b or b in a or ('小浜' in other['name'] and '北信越' in event['name']))
        if not any(same_event(e) for e in events):
            event['checkedAt'] = fetcher.records[event.get('scheduleSourceUrl', event['sourceUrl'])]['checkedAt']
            apply_event_overrides(event, overrides)
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
    for source in config.get('htmlResults', []):
        event = next((e for e in events if e['sourceUrl'] == source['eventUrl']), None)
        if event is None:
            continue
        try:
            results, problems = parse_jva_final_standings(fetcher.get(source['url']), source['url'])
            for problem in problems:
                issues.append({'url': source['url'], 'eventId': event['id'], 'kind': 'result', 'message': problem})
            if results:
                checked_at = fetcher.records[source['url']]['checkedAt']
                for result in results:
                    result['checkedAt'] = checked_at
                event['entries'] = results
                event['entryStatus'] = 'published'
                event['documents'].append({'url': source['url'], 'label': '公式最終順位（JVA）', 'kind': 'result', 'gender': None})
        except Exception as error:
            issues.append({'url': source['url'], 'kind': 'result', 'message': str(error)})
    collect_volleyball_world(events, fetcher, config, profiles, overrides.get('aliases', {}), issues, as_of)
    history, history_pdfs = collect_history(fetcher, config, as_of)
    for result_event in history:
        existing_index = next((i for i, event in enumerate(events)
                               if event['sourceUrl'] == result_event['sourceUrl']), None)
        if existing_index is None:
            events.append(result_event)
            continue
        pending_event = events[existing_index]
        result_event['venue'] = result_event.get('venue') or pending_event.get('venue', '')
        completed_genders = {entry['gender'] for entry in result_event['entries']}
        result_event['entries'].extend(
            entry for entry in pending_event['entries']
            if entry['gender'] not in completed_genders
        )
        known_documents = {document['url'] for document in result_event['documents']}
        result_event['documents'].extend(
            document for document in pending_event['documents']
            if document['url'] not in known_documents and document['kind'] != 'result'
        )
        events[existing_index] = result_event
    retain_unresolved_events(
        events,
        old['events'] if old else [],
        as_of,
        old['players'] if old else [],
    )
    pdf_count += history_pdfs
    if pdf_count > config['maxPdfs']:
        raise ValueError('結果PDFを含む取得上限超過')
    players = compile_players(events, profiles, overrides.get('aliases', {}))
    dataset = {'schemaVersion': 1, 'generatedAt': now(), 'checkedAt': max(r['checkedAt'] for r in fetcher.records.values()), 'asOf': as_of, 'year': config['year'],
               'coverage': {'source': 'JBV・JVA・Volleyball World・各大会主催者',
                            'description': 'JBVの年間予定・ニュース・公認大会、JVA国際大会予定、Volleyball Worldの公式チーム表から、公開済みの大会と日本選手の参加情報を選手に紐付けています。海外大会はJPNのペアと日本が関係する公式試合だけを収録し、海外の対戦相手は試合内の名前と国コードだけを表示します。開催後も大会と選手の紐付けを保持し、公式最終結果が未発表の場合は「順位確認中」と表示します。未発表の出場・順位は推測しません。',
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
