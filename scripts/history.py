"""Reviewed JVA final-ranking sources. Never derive placements from pool/bracket results."""
import io
import re
import pdfplumber
from scripts.parsers import normalize, soup_body, safe_url, dates_from_label, stable_id


def parse_results(raw, year, corrections=None):
    teams = []
    corrections = corrections or {}
    used = set()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            text = normalize(page.extract_text() or '')
            match = re.search(r'試合結果順位【(男子|女子)】', text)
            if not match:
                continue
            if f'tour{year}' not in text:
                raise ValueError('結果PDFの年度を確認してください')
            gender = 'men' if match[1] == '男子' else 'women'
            found = False
            for table in page.extract_tables():
                if len(table) < 3 or normalize(table[0][0]) not in ('順位', 'rank'):
                    continue
                columns = [i for i, cell in enumerate(table[1]) if cell == '氏名']
                if len(columns) != 2:
                    raise ValueError('結果表の氏名列が想定外です')
                found = True
                rank_label = None
                for row in table[2:]:
                    names = [' '.join((row[c] or '').split()) for c in columns]
                    if not all(names):
                        raise ValueError('結果表に氏名のない行があります')
                    key = f'{page_number}:{names[0]}'
                    label = row[0]
                    if key in corrections:
                        correction = corrections[key]
                        if label != correction['expected']:
                            raise ValueError('結果表が変更されました。手動補正を再確認してください')
                        label = correction['label']
                        used.add(key)
                    # None means a genuine vertically merged cell; an empty cell
                    # is ambiguous and must never inherit the preceding placement.
                    if label is not None:
                        rank_label = normalize(label)
                    if not rank_label or not re.fullmatch(r'優勝|準優勝|[1-9]\d*(位)?', rank_label):
                        raise ValueError(f'順位が不明: {page_number}ページ {names}')
                    rank = {'優勝': 1, '準優勝': 2}.get(rank_label)
                    rank = rank or int(rank_label.removesuffix('位'))
                    display = rank_label if not rank_label.isdigit() else f'{rank}位'
                    teams.append({'names': names, 'gender': gender, 'status': 'completed',
                                  'rank': rank, 'resultLabel': display, 'page': page_number})
            if not found:
                raise ValueError('最終順位ページの表を解析できません')
    if used != set(corrections):
        raise ValueError('手動補正の対象行が見つかりません')
    if not teams:
        raise ValueError('明示された最終順位表がありません')
    return teams


def parse_jbv_rankings(raw, gender):
    """Parse the explicit final-ranking table used by JBV satellite PDFs."""
    teams = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            text = normalize(page.extract_text() or '')
            if '最終順位' not in text:
                continue
            tables = page.extract_tables()
            for table in tables:
                if not table or normalize(table[0][0]) != '順位':
                    continue
                rank = None
                for row in table[1:]:
                    label = row[0]
                    if label is not None:
                        label = normalize(label)
                        match = re.fullmatch(r'(\d+)位', label)
                        if not match:
                            raise ValueError(f'JBV最終順位が不明: {label}')
                        rank = int(match[1])
                    if rank is None:
                        raise ValueError('JBV最終順位の結合セルを確認できません')
                    surnames = (row[1] or '').splitlines()
                    given = (row[2] or '').splitlines()
                    if len(surnames) != 2 or len(given) != 2:
                        raise ValueError(f'JBV最終順位の氏名列が想定外です: {row}')
                    teams.append({
                        'names': [f'{a} {b}' for a, b in zip(surnames, given)],
                        'gender': gender,
                        'status': 'completed',
                        'rank': rank,
                        'resultLabel': f'{rank}位',
                        'page': page_number,
                    })
    if not teams:
        raise ValueError('JBVの明示された最終順位表がありません')
    return teams


def collect_history(fetcher, config, as_of):
    settings = config.get('history')
    if not settings:
        return [], 0
    index = settings['indexUrl']
    soup, _ = soup_body(fetcher.get(index))
    events, pdf_count = [], 0
    for source in settings['events']:
        url = source['url']
        link = next((a for a in soup.select('a[href]') if a['href'] == url), None)
        dl = link.find_parent('dl') if link else None
        if dl is None:
            raise ValueError(f'年間予定から過去大会が消えています: {url}')
        label = dl.find('dt').get_text(' ', strip=True)
        start, end = dates_from_label(label, config['year'])
        if not start:
            raise ValueError(f'過去大会の日付が不明: {url}')
        if end >= as_of:
            continue
        results_url = url + '?entry=schedule_results'
        results, _ = soup_body(fetcher.get(results_url))
        docs = []
        for a in results.select('a[href]'):
            doc_url = safe_url(results_url, a['href'])
            if doc_url and doc_url.endswith('.pdf') and '結果' in a.get_text():
                if doc_url not in [d['url'] for d in docs]:
                    docs.append({'url': doc_url, 'label': a.get_text(' ', strip=True), 'kind': 'result', 'gender': None})
        if not docs or len(docs) > 4:
            raise ValueError(f'結果資料の掲載を再確認してください: {results_url}')
        entries = []
        for doc in docs:
            pdf_count += 1
            entries += [dict(team, sourceUrl=doc['url']+f'#page={team["page"]}',
                             checkedAt=fetcher.records[doc['url']]['checkedAt'])
                        for team in parse_results(fetcher.get(doc['url']), config['year'],
                                                  source.get('corrections', {}).get(doc['url']))]
            doc['parsed'] = True
        if sorted(set(e['gender'] for e in entries)) != sorted(source['genders']):
            raise ValueError(f'結果の男女区分が変わっています: {url}')
        name = link.get_text(' ', strip=True)
        venue = dl.select_one('.schedule-contents-dl-place')
        events.append({'id': stable_id('e-', url), 'name': name, 'officialTitle': name,
                       'category': 'BVT1', 'startDate': start, 'endDate': end, 'dateLabel': label,
                       'venue': venue.get_text(' ', strip=True) if venue else '', 'cancelled': False,
                       'sourceUrl': url, 'scheduleSourceUrl': index, 'documents': docs,
                       'entries': entries, 'entryStatus': 'published', 'resultCoverage': source['coverage'],
                       'checkedAt': fetcher.records[results_url]['checkedAt']})
    for source in settings.get('directEvents', []):
        if source['endDate'] >= as_of:
            continue
        page, _ = soup_body(fetcher.get(source['url']))
        page_text = normalize(page.get_text(' ', strip=True))
        if normalize(source['name']) not in page_text:
            raise ValueError(f'過去大会ページの内容が変わっています: {source["url"]}')
        entries, docs = [], []
        for document in source['documents']:
            pdf_count += 1
            parser = document['parser']
            raw = fetcher.get(document['url'])
            if parser == 'jbv-ranking':
                parsed = parse_jbv_rankings(raw, document['gender'])
            else:
                raise ValueError(f'未対応の過去結果形式: {parser}')
            entries += [dict(team, sourceUrl=document['url'] + f'#page={team["page"]}',
                             checkedAt=fetcher.records[document['url']]['checkedAt'])
                        for team in parsed]
            docs.append({'url': document['url'], 'label': document['label'], 'kind': 'result',
                         'gender': document['gender'], 'parsed': True})
        events.append({
            'id': stable_id('e-', source['url']), 'name': source['name'],
            'officialTitle': source['name'], 'category': source['category'],
            'startDate': source['startDate'], 'endDate': source['endDate'],
            'dateLabel': source['dateLabel'], 'venue': source['venue'], 'cancelled': False,
            'sourceUrl': source['url'], 'documents': docs, 'entries': entries,
            'entryStatus': 'published', 'resultCoverage': source['coverage'],
            'checkedAt': fetcher.records[source['url']]['checkedAt'],
        })
    return events, pdf_count
