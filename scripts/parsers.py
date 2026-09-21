"""Conservative, deterministic parsers. Unknown layouts go to review, never guesses."""
import hashlib
import io
import re
import unicodedata
from datetime import date
from urllib.parse import urljoin, urlparse

import pdfplumber
from bs4 import BeautifulSoup


def normalize(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).translate(str.maketrans("髙﨑", "高崎")).lower()


def stable_id(prefix, value):
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:14]


def safe_url(base, href):
    url = urljoin(base, href).split('#')[0]
    return url if urlparse(url).scheme in ('https', 'http') else None


def soup_body(html):
    soup = BeautifulSoup(html, 'html.parser')
    return soup, soup.select_one('#contents_Right') or soup.select_one('main') or soup


def dates_from_label(value, year):
    """Only parse a labelled event date, never a publication/entry deadline."""
    value = unicodedata.normalize('NFKC', value)
    full = re.search(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日', value)
    if full:
        y, m, d = map(int, full.groups())
    else:
        full = re.search(r'(\d{1,2})\s*[/月]\s*(\d{1,2})', value)
        if not full:
            return None, None
        y, (m, d) = year, map(int, full.groups())
    try:
        start = date(y, m, d)
        tail = value[full.end():]
        # Limit to a following date, excluding start times and update annotations.
        endmatch = re.match(r'(?:日)?\s*(?:\([^)]*\))?\s*[~～〜・、,\-]\s*(?:(20\d{2})年)?(?:(\d{1,2})[/月])?(\d{1,2})(?:日|\(|$)', tail)
        end = start
        if endmatch:
            ey, em, ed = endmatch.groups()
            em = int(em) if em else m
            ey = int(ey) if ey else y + (em < m)
            end = date(ey, em, int(ed))
        if end < start:
            return None, None
        return start.isoformat(), end.isoformat()
    except ValueError:
        return None, None


def parse_profiles(html, url):
    soup, _ = soup_body(html)
    result = []
    for a in soup.select('dd a[href]'):
        href = safe_url(url, a['href'])
        if not href or not re.search(r'/players/(man|woman)/', href):
            continue
        parts = list(a.stripped_strings)
        if parts:
            result.append({'name': parts[0], 'roman': parts[1] if len(parts) > 1 else '',
                           'gender': 'women' if '/woman/' in href else 'men', 'profileUrl': href})
    return result


def parse_article(html, url, year):
    _, body = soup_body(html)
    heading = body.find('h2')
    if not heading:
        return None
    title = heading.get_text(' ', strip=True)
    content = body.select_one('.release_entry') or body
    lines = list(content.stripped_strings)
    text = '\n'.join(lines)
    date_label = next((re.split(r'[／/:：]', x, maxsplit=1)[-1].strip() for x in lines
                       if re.match(r'^[◆●■\s]*(開催期間|開催日程|開催日時|開催日|日程|期日)[／/:：]', x)), '')
    # Some announcements put one date per following line (e.g. U20 小浜).
    label_index = next((i for i, x in enumerate(lines) if re.match(r'^[◆●■\s]*(開催期間|開催日程|開催日時|開催日|日程|期日)[／/:：]', x)), None)
    if label_index is not None:
        extra = []
        for line in lines[label_index + 1:label_index + 5]:
            if re.match(r'^[◆●■]|^(会場|募集|競技|申込)', line):
                break
            if re.search(r'20\d{2}年\d{1,2}月\d{1,2}日', line):
                extra.append(line)
        if extra:
            date_label += ' / ' + ' / '.join(extra)
    venue = next((re.split(r'[／/:：]', x, maxsplit=1)[-1].strip() for x in lines
                  if re.match(r'^[◆●■\s]*(会場|開催会場|開催地)[／/:：]', x)), '')
    if not date_label or not re.search(r'大会|カップ|選手権|シリーズ|キング|CUP|Cup|cup', title):
        return None
    start, end = dates_from_label(date_label, year)
    explicit_dates = re.findall(r'20\d{2}年\d{1,2}月\d{1,2}日', unicodedata.normalize('NFKC', date_label))
    if len(explicit_dates) > 1:
        parsed = [dates_from_label(x, year)[0] for x in explicit_dates]
        if all(parsed):
            start, end = min(parsed), max(parsed)
    cat = re.search(r'【([^】]+)】', title)
    name = re.sub(r'＜[^＞]+＞', '', re.sub(r'^【[^】]+】\s*', '', title))
    name = re.split(r'参加チーム|エントリー|シーディング|開催中止|／開催中止|大会結果', name)[0].rstrip('／・ ')
    if name.endswith('結果'):
        name = name[:-2]
    # Keep the complete official title separately for attribution/debugging.
    documents = []
    for a in content.select('a[href]'):
        link = safe_url(url, a['href'])
        if not link or not urlparse(link).path.lower().endswith('.pdf'):
            continue
        label = a.get_text(' ', strip=True).lstrip('◆ ')
        if any(d['url'] == link for d in documents):
            continue
        gender = 'women' if re.search(r'女子|women|female', label+' '+link, re.I) else 'men' if re.search(r'男子|(?<!wo)men|male', label+' '+link, re.I) else None
        kind = ('seed' if re.search(r'シーディング|seedlist', label+' '+link, re.I) else
                'entry' if re.search(r'参加チーム|出場チーム|エントリーリスト|entrylist', label+' '+link, re.I) else
                'schedule' if re.search(r'スケジュール|スケシュール|対戦表|組合せ|組み合わせ|schedule', label+' '+link, re.I) else 'info')
        documents.append({'url': link, 'label': label, 'kind': kind, 'gender': gender})
    return {'id': stable_id('e-', url), 'name': name, 'officialTitle': title, 'category': cat.group(1) if cat else '公認大会',
            'startDate': start, 'endDate': end, 'dateLabel': date_label, 'venue': venue,
            'cancelled': bool(re.search(r'開催中止|大会中止', title)), 'sourceUrl': url,
            'documents': documents, 'entries': [], 'entryStatus': 'unpublished'}


def parse_calendar(html, url, year):
    """JBV annual schedule: expand rowspans before identifying date and venue."""
    _, body = soup_body(html)
    events = []
    for table in body.select('table'):
        heading = table.find_previous('h2')
        category = heading.get_text(' ', strip=True) if heading else '年間予定'
        carried = {}
        for ri, tr in enumerate(table.select('tr')):
            cells, ci = {}, 0
            for index, (remaining, text) in list(carried.items()):
                cells[index] = text
                if remaining == 1:
                    del carried[index]
                else:
                    carried[index] = (remaining - 1, text)
            if tr.find('th'):
                continue
            for td in tr.find_all('td', recursive=False):
                while ci in cells:
                    ci += 1
                cells[ci] = td.get_text(' ', strip=True)
                if int(td.get('rowspan', 1)) > 1:
                    carried[ci] = (int(td['rowspan']) - 1, cells[ci])
                ci += 1
            date_col = next((i for i, value in sorted(cells.items()) if re.match(r'^\d{1,2}/\d{1,2}', value)), None)
            if date_col is None:
                continue
            label = cells[date_col]
            start, end = dates_from_label(label.split('※')[0], year)
            name = ' '.join(cells[i] for i in sorted(cells) if i < date_col)
            venue = cells.get(date_col+1, '')
            if not start or not name:
                continue
            category_short = 'BVT3' if 'アンダーエイジ' in category else 'BVT2' if 'サテライト' in category else 'JBVs' if 'JBVシリーズ' in category else 'JBVc' if 'チャレンジャー' in category else '大会'
            events.append({'id': stable_id('e-', url+'|'+name+'|'+start), 'name': name, 'officialTitle': name,
                           'category': category_short, 'startDate': start, 'endDate': end, 'dateLabel': label,
                           'venue': venue, 'cancelled': '中止' in label, 'sourceUrl': url,
                           'documents': [], 'entries': [], 'entryStatus': 'unpublished'})
    return events


def parse_jva_calendar(html, url, year):
    _, body = soup_body(html)
    events = []
    for dl in body.select('dl.is-beach_international'):
        dt, title = dl.find('dt'), dl.select_one('.schedule-contents-dl-title')
        if dt is None or title is None:
            continue
        label = dt.get_text(' ', strip=True)
        start, end = dates_from_label(label, year)
        if not start:
            continue
        a = title.find('a')
        name = title.get_text(' ', strip=True)
        source = safe_url(url, a['href']) if a else url
        venue = dl.select_one('.schedule-contents-dl-place')
        events.append({'id': stable_id('e-', source if a else source+'|'+name+'|'+start),
                       'name': name, 'officialTitle': name, 'category': '国際大会',
                       'startDate': start, 'endDate': end, 'dateLabel': label,
                       'venue': venue.get_text(' ', strip=True) if venue else '',
                       'cancelled': '中止' in name, 'sourceUrl': source, 'scheduleSourceUrl': url,
                       'documents': [], 'entries': [], 'entryStatus': 'unpublished'})
    return events


def parse_jva_teams(html, profiles):
    """JVA groups each actual pair in a separate m-playerList section.

    Never pair arbitrary adjacent names or use the overall national-team list
    as evidence of entry. Sex is resolved against already verified profiles.
    """
    _, body = soup_body(html)
    genders = {normalize(p['name']): p['gender'] for p in profiles}
    teams, problems = [], []
    for section in body.select('section.m-playerList'):
        names = [n.get_text(' ', strip=True) for n in section.select('.m-playerList-contents-article-data-name')]
        if not names:
            continue
        group_genders = {genders[normalize(n)] for n in names if normalize(n) in genders}
        if len(names) != 2 or len(group_genders) != 1:
            problems.append('JVAのペア区分・男女区分を確認してください: ' + ' / '.join(names))
            continue
        teams.append({'names': names, 'gender': group_genders.pop(), 'status': 'entered', 'number': len(teams)+1})
    if not teams and not problems:
        problems.append('JVAの出場メンバー欄を検出できません。未発表か形式変更かを確認してください')
    return (teams if not problems else []), problems


def parse_roster(data, gender):
    """Read ruled two-player JBV tables by columns; ignore bracket-only pages."""
    teams, issues = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pageno, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ''
            if len(text.strip()) < 20:
                issues.append(f'{pageno}ページ: 文字データなし（画像PDF。OCR・目視確認が必要）')
                continue
            for table in page.extract_tables():
                # Roster continuation pages can have no header, but retain 5 columns.
                for row in table:
                    if len(row) != 5 or not row[0] or not row[1]:
                        continue
                    marker = unicodedata.normalize('NFKC', row[0])
                    if not re.match(r'^\d{1,3}(?:\s|$)', marker):
                        continue
                    names = [re.sub(r'\s+', ' ', n).strip() for n in row[1].splitlines() if n.strip()]
                    if len(names) != 2 or any(re.search(r'\d|勝者|敗者|氏名|チーム', n) for n in names):
                        issues.append(f'{pageno}ページ: チーム{marker}の氏名欄を確認してください')
                        continue
                    if not row[3] or not re.fullmatch(r'[\d\s,]+', row[3]):
                        continue
                    status = 'reserve' if '補欠' in marker else 'entered'
                    if re.search(r'取消|欠場|棄権', marker):
                        status = 'withdrawn'
                    teams.append({'names': names, 'gender': gender, 'status': status,
                                  'number': int(re.match(r'\d+', marker)[0]), 'page': pageno})
    seen = set()
    for team in teams:
        key = tuple(normalize(n) for n in team['names'])
        if key in seen:
            issues.append('同一ペアが複数行にあります')
        seen.add(key)
    if not teams:
        issues.append('対応する2人制の名簿テーブルがありません。公式資料で確認してください')
    # Reject the whole roster on any ambiguity: no silent partial publication.
    return (teams if not issues else []), issues
