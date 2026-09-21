import io
import unittest
from unittest.mock import patch, MagicMock
from scripts.parsers import dates_from_label, parse_article, parse_calendar, parse_roster, parse_jva_calendar, parse_jva_teams, normalize
from scripts.update import compile_players, validate


class ParsersTest(unittest.TestCase):
    def test_date_ranges(self):
        for text, start, end in [
            ('2026年9月26日(土)～27日(日)試合開始9:30', '2026-09-26', '2026-09-27'),
            ('10/31(土)・11/1(日)', '2026-10-31', '2026-11-01'),
            ('9/11-13', '2026-09-11', '2026-09-13'),
            ('10/10,11', '2026-10-10', '2026-10-11'),
            ('調整中', None, None), ('2026年2月30日', None, None)]:
            with self.subTest(text=text): self.assertEqual(dates_from_label(text, 2026), (start, end))

    def test_separate_days_and_deadline(self):
        html = '''<div id="contents_Right"><h2>【BVT3】U20小浜大会エントリー受付中</h2><div class="release_entry">
        ◆開催期間／2大会開催<br>【1日目】2026年10月11日(日)<br>【2日目】2026年10月12日(月)<br>
        ◆会場／海岸<br>◆申込期限／2026年9月28日(月)</div></div>'''
        e = parse_article(html, 'https://www.jbv.jp/news/entry-1.html', 2026)
        self.assertEqual((e['startDate'], e['endDate']), ('2026-10-11', '2026-10-12'))
        self.assertEqual(e['venue'], '海岸')

    def test_no_inference_from_publication_date(self):
        html = '<div id="contents_Right"><h2>大会のお知らせ</h2><div class="release_entry">2026年9月22日<br>◆申込期限／2026年10月1日</div></div>'
        self.assertIsNone(parse_article(html, 'https://www.jbv.jp/news/x.html', 2026))

    def test_calendar_rowspans_and_cancellation(self):
        html = '<div id="contents_Right"><h2>アンダーエイジ</h2><table><tr><th>地域</th></tr><tr><td rowspan="2">関東</td><td>U20</td><td>10/11(日) ※中止</td><td>越谷</td></tr><tr><td>U18</td><td>11/1(日)</td><td>横浜</td></tr></table></div>'
        events = parse_calendar(html, 'https://www.jbv.jp/convention/index.html', 2026)
        self.assertTrue(events[0]['cancelled'])
        self.assertEqual(events[1]['name'], '関東 U18')

    def roster(self, rows):
        page = MagicMock()
        page.extract_text.return_value = '参加チーム一覧 氏名 所属 オフィシャルポイント 男子'
        page.extract_tables.return_value = [rows]
        doc = MagicMock(); doc.__enter__.return_value.pages = [page]
        with patch('scripts.parsers.pdfplumber.open', return_value=doc):
            return parse_roster(b'', 'men')

    def test_reserves_are_not_entrants(self):
        teams, issues = self.roster([['1', '選手 一\n選手 二', '大学', '100', '200'], ['25\n補欠', '選手 三\n選手 四', '', '50', '100']])
        self.assertFalse(issues)
        self.assertEqual([x['status'] for x in teams], ['entered', 'reserve'])

    def test_ambiguous_pdf_is_not_partially_published(self):
        teams, issues = self.roster([['1', '選手 一\n選手 二', '', '100', '200'], ['2', '選手 三', '', '100', '200']])
        self.assertFalse(teams)
        self.assertTrue(issues)

    def test_aliases_keep_one_player(self):
        events = [{'entries': [{'names': ['Kaufer Martin', '髙橋 大地'], 'gender': 'men'}]}, {'entries': [{'names': ['Martin Kaufer', '高橋大地'], 'gender': 'men'}]}]
        players = compile_players(events, [], {'Kaufer Martin': 'Martin Kaufer'})
        self.assertEqual(len(players), 2)
        self.assertEqual(events[0]['entries'][0]['playerIds'], events[1]['entries'][0]['playerIds'])

    def test_jva_uses_explicit_pair_sections(self):
        html = '''<main><section class="m-playerList"><div class="m-playerList-contents-article-data-name">選手 一</div><div class="m-playerList-contents-article-data-name">選手 二</div></section></main>'''
        profiles = [{'name': '選手一', 'gender': 'women'}, {'name': '選手二', 'gender': 'women'}]
        teams, issues = parse_jva_teams(html, profiles)
        self.assertFalse(issues)
        self.assertEqual(teams[0]['names'], ['選手 一', '選手 二'])
        self.assertEqual(teams[0]['gender'], 'women')
        html = html.replace('</section>', '<div class="m-playerList-contents-article-data-name">選手 三</div></section>')
        self.assertFalse(parse_jva_teams(html, profiles)[0])

    def test_jva_date_and_source(self):
        html = '''<main><dl class="is-beach_international"><dt>9/20-10/3</dt><dd class="schedule-contents-dl-title"><a href="event/">国際大会</a></dd><dd class="schedule-contents-dl-place">愛知</dd></dl></main>'''
        event = parse_jva_calendar(html, 'https://www.jva.or.jp/beach_international/2026/', 2026)[0]
        self.assertEqual(event['endDate'], '2026-10-03')
        self.assertEqual(event['sourceUrl'], 'https://www.jva.or.jp/beach_international/2026/event/')


if __name__ == '__main__': unittest.main()
