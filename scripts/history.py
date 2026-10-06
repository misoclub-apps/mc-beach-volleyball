"""Reviewed JVA final-ranking sources. Never derive placements from pool/bracket results."""
import io
import re
import pdfplumber
from scripts.parsers import normalize, soup_body, safe_url, dates_from_label, stable_id, parse_article


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
    """Parse explicit official ranking tables used by JBV and JVA PDFs."""
    teams = []

    def rank_value(label):
        label = normalize(label)
        if label in ('優勝', '準優勝'):
            return {'優勝': (1, '優勝'), '準優勝': (2, '準優勝')}[label]
        match = re.fullmatch(r'(\d+)(?:位)?', label)
        return (int(match[1]), f'{int(match[1])}位') if match else None

    def table_gender(table, page_text):
        if gender:
            return gender
        heading = normalize(' '.join(str(cell or '') for row in table[:2] for cell in row))
        if '男子' in heading:
            return 'men'
        if '女子' in heading:
            return 'women'
        # A one-table page can put the division only in the page heading.
        has_men, has_women = '男子' in page_text, '女子' in page_text
        if has_men != has_women:
            return 'men' if has_men else 'women'
        raise ValueError('JBV最終順位の男女区分が不明です')

    continuation = None
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            text = normalize(page.extract_text() or '')
            if (continuation is None
                    and not any(label in text for label in ('最終順位', '試合結果順位', 'ルーザートーナメント順位', '結果', '順位'))):
                continue
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                header_index = next((i for i, row in enumerate(table[:3])
                                     if normalize(row[0] or '') in ('順位', 'rank', 'no')), None)
                if header_index is None:
                    if continuation is None:
                        continue
                    first_label = normalize(table[0][0] or '')
                    if first_label and not rank_value(first_label) and first_label not in ('棄権', '失格'):
                        continuation = None
                        continue
                    name_columns = continuation['name_columns']
                    combined_column = continuation['combined_column']
                    header = continuation['header']
                    header_count = 0
                    division = continuation['division']
                    rank = continuation['rank']
                    display = continuation['display']
                    data_start = 0
                else:
                    header = [normalize(cell or '') for cell in table[header_index]]
                    subheader = ([normalize(cell or '') for cell in table[header_index + 1]]
                                 if header_index + 1 < len(table) else [])
                    header_name_columns = [i for i, cell in enumerate(header) if cell in ('氏名', 'name')]
                    subheader_name_columns = [i for i, cell in enumerate(subheader) if cell in ('氏名', 'name')]
                    if header_name_columns:
                        name_columns, header_count = header_name_columns, 1
                    elif subheader_name_columns:
                        name_columns, header_count = subheader_name_columns, 2
                    else:
                        name_columns = [i for i, cell in enumerate(header)
                                        if re.fullmatch(r'(?:選手|player)[12１２]?', cell)]
                        header_count = 1
                    combined_column = next((i for i, cell in enumerate(header)
                                            if cell in ('氏名(所属)', '氏名（所属）')), None)
                    if combined_column is not None:
                        name_columns = [combined_column]
                    if not 1 <= len(name_columns) <= 2:
                        continue
                    division = table_gender(table, text)
                    rank = None
                    display = None
                    data_start = header_index + header_count
                for row in table[data_start:]:
                    label = row[0]
                    if label is not None:
                        normalized_label = normalize(label)
                        if normalized_label in ('棄権', '失格'):
                            rank = None
                            continue
                        parsed_rank = rank_value(normalized_label)
                        if not parsed_rank:
                            raise ValueError(f'JBV最終順位が不明: {normalized_label}')
                        rank, display = parsed_rank
                    if rank is None:
                        raise ValueError('JBV最終順位の結合セルを確認できません')
                    if combined_column is not None:
                        first = [' '.join(name.split()) for name in (row[combined_column] or '').splitlines() if name.strip()]
                        adjacent = ([' '.join(name.split()) for name in (row[combined_column + 1] or '').splitlines() if name.strip()]
                                    if combined_column + 1 < len(row) else [])
                        if (len(first) == len(adjacent) == 2
                                and not all(re.search(r'\s', name) for name in first)):
                            names = [f'{surname} {given}' for surname, given in zip(first, adjacent)]
                        else:
                            names = first
                    elif len(name_columns) == 2:
                        if header_count == 1 and all(
                            column + 1 < len(header) and not header[column + 1]
                            for column in name_columns
                        ):
                            names = [f'{row[column] or ""} {row[column + 1] or ""}'.strip()
                                     for column in name_columns]
                        else:
                            names = [' '.join((row[column] or '').split()) for column in name_columns]
                    else:
                        # Satellite tables split each player's surname and given name
                        # across adjacent cells under two repeated 氏名 headers.
                        column = name_columns[0]
                        repeated = [i for i, cell in enumerate(header) if cell == header[column]]
                        if len(repeated) == 2 and all(i + 1 < len(row) for i in repeated):
                            names = [f'{row[i] or ""} {row[i + 1] or ""}'.strip() for i in repeated]
                        else:
                            names = [' '.join((row[column] or '').split())]
                    if not names or any(not name for name in names):
                        raise ValueError(f'JBV最終順位の氏名列が想定外です: {row}')
                    teams.append({
                        'names': names,
                        'gender': division,
                        'status': 'completed',
                        'rank': rank,
                        'resultLabel': display,
                        'page': page_number,
                    })
                continuation = {'name_columns': name_columns, 'combined_column': combined_column,
                                'header': header, 'division': division, 'rank': rank,
                                'display': display}
    if not teams:
        raise ValueError('JBVの明示された最終順位表がありません')
    return teams


def verify_direct_result_links(page, page_url, documents):
    """Catch a result article that silently replaced its configured PDF links."""
    published = {safe_url(page_url, link['href']) for link in page.select('a[href]')}
    missing = [document['url'] for document in documents if document['url'] not in published]
    if missing:
        raise ValueError(f'公式記事の結果PDFリンクが変更されました: {missing}')


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
        page_url = source.get('pageUrl', source['url'])
        page_raw = fetcher.get(page_url)
        page, _ = soup_body(page_raw)
        page_text = normalize(page.get_text(' ', strip=True))
        if normalize(source.get('matchText', source['name'])) not in page_text:
            raise ValueError(f'過去大会ページの内容が変わっています: {page_url}')
        if source.get('requireDocumentLinks'):
            verify_direct_result_links(page, page_url, source['documents'])
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
        article = parse_article(page_raw, page_url, config['year'])
        venue = source.get('venue') or (article.get('venue', '') if article else '')
        events.append({
            'id': stable_id('e-', source['url']), 'name': source['name'],
            'officialTitle': source['name'], 'category': source['category'],
            'startDate': source['startDate'], 'endDate': source['endDate'],
            'dateLabel': source['dateLabel'], 'venue': venue, 'cancelled': False,
            'sourceUrl': source['url'], 'documents': docs, 'entries': entries,
            'entryStatus': 'published', 'resultCoverage': source.get('coverage', ''),
            'checkedAt': fetcher.records[page_url]['checkedAt'],
        })
    return events, pdf_count
