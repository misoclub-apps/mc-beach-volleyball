"""Prepare an agent-readable source dossier, including links embedded in PDFs.

This is deliberately separate from publishing: discovering a link is not evidence
that its contents describe an entrant. Review reports, then adapt parsers/overrides.
"""
import json
from urllib.parse import urlparse
import pymupdf
from scripts.update import ROOT, Fetcher, write_json
from scripts.parsers import soup_body, safe_url


def main():
    config = json.loads((ROOT / 'config/sources.json').read_text())
    data = json.loads((ROOT / 'public/data/beach.json').read_text())
    fetch = Fetcher(config['requestIntervalSeconds'], allowed_hosts=config['allowedHosts'])
    fetch.check_robots()
    records, candidates = [], {}
    for event in data['events']:
        if event['cancelled']:
            continue
        print(event['name'], flush=True)
        source = event['sourceUrl']
        _, body = soup_body(fetch.get(source))
        urls = [(safe_url(source, a['href']), a.get_text(' ', strip=True)) for a in body.select('a[href]')]
        for doc in event['documents']:
            if not urlparse(doc['url']).path.lower().endswith('.pdf'):
                urls.append((doc['url'], doc['label']))
                continue
            try:
                raw = fetch.get(doc['url'])
                with pymupdf.open(stream=raw, filetype='pdf') as pdf:
                    text = '\n'.join(p.get_text() for p in pdf)
                    links = [link['uri'] for p in pdf for link in p.get_links() if link.get('uri')]
                records.append({'eventId': event['id'], 'url': doc['url'], 'label': doc['label'], 'text': text, 'links': links})
                urls += [(u, doc['label'] + '（PDF内リンク）') for u in links]
            except Exception as error:
                records.append({'eventId': event['id'], 'url': doc['url'], 'error': str(error)})
        for url, label in urls:
            if not url or urlparse(url).scheme not in ('https', 'http'):
                continue
            host = urlparse(url).hostname
            if host in ('www.jbv.jp', 'jbv.jp'):
                continue
            if any(social in host for social in ['twitter.com', 'facebook.com', 'instagram.com', 'google.com', 'google.co.jp', 'forms.gle', 'youtube.com', 'jvamrs.jp']):
                continue
            candidates[url] = {'url': url, 'label': label, 'foundOn': source, 'eventId': event['id'], 'host': host}
    write_json(ROOT / 'reports/pdf-review.json', records)
    write_json(ROOT / 'reports/external-candidates.json', list(candidates.values()))
    print(json.dumps(list(candidates.values()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
