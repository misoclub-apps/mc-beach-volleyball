import io
import unittest
from unittest.mock import patch, MagicMock
from scripts.parsers import dates_from_label, parse_article, parse_calendar, parse_profile_image, parse_profiles, parse_roster, parse_jva_calendar, parse_jva_teams, parse_volleyball_world_final_standings, parse_volleyball_world_match, parse_volleyball_world_teams, normalize
from scripts.update import apply_event_overrides, compile_players, merge_volleyball_world_entries, retain_unresolved_events, validate


class ParsersTest(unittest.TestCase):
    def test_profile_photo_comes_from_official_player_card(self):
        html = '''<dl><dt><a href="woman/sakai.html"><img src="img/woman/sakai_w.jpg"></a></dt>
        <dd><a href="woman/sakai.html">酒井春海<br><span>Harumi Sakai</span></a></dd></dl>'''
        profile = parse_profiles(html, 'https://www.jbv.jp/players/index.html')[0]
        self.assertEqual(profile['imageUrl'], 'https://www.jbv.jp/players/img/woman/sakai_w.jpg')
        self.assertEqual(profile['profileUrl'], 'https://www.jbv.jp/players/woman/sakai.html')

    def test_individual_profile_photo_replaces_directory_thumbnail(self):
        html = '''<div id="contents_Right"><img src="../../cmn/logo.jpg" alt="JBV">
        <img src="../img/woman/pic/sakai.jpg" alt="酒井春海"></div>'''
        image = parse_profile_image(html, 'https://www.jbv.jp/players/woman/sakai.html', '酒井 春海')
        self.assertEqual(image, 'https://www.jbv.jp/players/img/woman/pic/sakai.jpg')
        self.assertIsNone(parse_profile_image(html, 'https://www.jbv.jp/players/woman/sakai.html', '別の選手'))

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

    def test_spaced_venue_label(self):
        html = '''<div id="contents_Right"><h2>聖地浜松カップ2026結果</h2><div class="release_entry">
        ◆開催日／2026年5月16日(土)<br>
        ◆会　場／静岡県浜松市・遠州灘海浜公園江之島ビーチコート</div></div>'''
        event = parse_article(html, 'https://www.jbv.jp/news/entry-2.html', 2026)
        self.assertEqual(event['venue'], '静岡県浜松市・遠州灘海浜公園江之島ビーチコート')

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

    def test_detail_link_can_keep_existing_public_event_id(self):
        event = {'id': 'e-new', 'sourceUrl': 'https://official.example/event/', 'venue': 'old'}
        overrides = {
            'eventIds': {'https://official.example/event/': 'e-existing'},
            'events': {'e-existing': {'venue': 'confirmed'}},
        }
        apply_event_overrides(event, overrides)
        self.assertEqual(event['id'], 'e-existing')
        self.assertEqual(event['venue'], 'confirmed')

    def test_ended_event_with_roster_is_kept_while_results_are_pending(self):
        previous = [{
            'id': 'e-past', 'sourceUrl': 'https://official.example/event/',
            'endDate': '2026-09-26', 'entryStatus': 'published',
            'entries': [
                {'status': 'entered', 'gender': 'women'},
                {'status': 'reserve', 'gender': 'women'},
            ],
        }]
        events = []
        self.assertEqual(retain_unresolved_events(events, previous, '2026-09-28'), 1)
        self.assertEqual(events[0]['entries'][0]['status'], 'resultPending')
        self.assertEqual(events[0]['entries'][1]['status'], 'reserve')
        self.assertEqual(events[0]['entryStatus'], 'resultPending')

    def test_missing_jva_layout_requires_review(self):
        teams, issues = parse_jva_teams('<main>掲載形式が変わりました</main>', [])
        self.assertFalse(teams)
        self.assertTrue(issues)

    def test_volleyball_world_keeps_only_japan_teams_and_stage(self):
        html = '''<table><tr data-team-no="123" data-team-country="JPN">
        <td class="player1">Riko Tsujimura</td><td class="player2">Mayu Kikuchi</td></tr>
        <tr data-team-no="456" data-team-country="GER"><td class="player1">Foreign One</td>
        <td class="player2">Foreign Two</td></tr></table>'''
        teams = parse_volleyball_world_teams(html, 'women', 'main-draw', 'https://official.example/teams')
        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0]['externalTeamId'], 123)
        self.assertEqual(teams[0]['internationalStage'], 'main-draw')

    def test_official_team_state_merges_without_replacing_japanese_names(self):
        event = {'entries': [
            {'names': ['辻村りこ', '菊地真結'], 'gender': 'women',
             'status': 'entered', 'sourceUrl': 'https://jva.example/'},
            {'names': ['旧名簿', '掲載ペア'], 'gender': 'women',
             'status': 'entered', 'sourceUrl': 'https://jva.example/'},
        ]}
        official = [{'names': ['Riko Tsujimura', 'Mayu Kikuchi'], 'gender': 'women',
                     'status': 'entered', 'internationalStage': 'main-draw',
                     'externalTeamId': 123, 'sourceUrl': 'https://world.example/'}]
        aliases = {'Riko Tsujimura': '辻村りこ', 'Mayu Kikuchi': '菊地真結'}
        merge_volleyball_world_entries(event, official, aliases)
        self.assertEqual(event['entries'][0]['names'], ['辻村りこ', '菊地真結'])
        self.assertEqual(event['entries'][0]['externalTeamId'], 123)
        self.assertEqual(event['entries'][0]['sourceUrl'], 'https://world.example/')
        self.assertEqual(len(event['entries']), 1)

    def test_volleyball_world_match_keeps_opponents_as_plain_names(self):
        html = '''<div class="vbw-match-header" data-match-no="99" data-date="2026-10-16T01:00:00Z">
        <div class="vbw-mu--match vbw-mu-finished"></div><div class="vbw-mu__data-info">Main Draw - Pool A</div>
        <div class="vbw-mu__team vbw-mu__team--home"><div class="vbw-mu__team__logo"><img src="/flag_jpn"></div>
        <div class="vbw-mu__team__player-wrap"><div class="vbw-mu__team__name">Tsujimura</div><div class="vbw-mu__team__name vbw-mu__team__name--abbr">T.</div></div>
        <div class="vbw-mu__team__player-wrap"><div class="vbw-mu__team__name">Kikuchi</div></div></div>
        <div class="vbw-mu__team vbw-mu__team--away"><div class="vbw-mu__team__logo"><img src="/flag_ger"></div>
        <div class="vbw-mu__team__player-wrap"><div class="vbw-mu__team__name">Foreign One</div></div>
        <div class="vbw-mu__team__player-wrap"><div class="vbw-mu__team__name">Foreign Two</div></div></div>
        <div class="vbw-mu__sets--result"><span class="vbw-mu__pointA">21</span><span class="vbw-mu__pointB">18</span></div>
        <div class="vbw-mu__score--home">2</div><div class="vbw-mu__score--away">0</div></div>'''
        match = parse_volleyball_world_match(html, 'https://official.example/match/99')
        self.assertEqual(match['home']['countryCode'], 'JPN')
        self.assertEqual(match['away']['names'], ['Foreign One', 'Foreign Two'])
        self.assertEqual(match['score'], [2, 0])

    def test_volleyball_world_final_standings_keep_shared_japan_rank(self):
        html = '''<table class="vbw-o-table"><tr><td>pool</td></tr></table>
        <table class="vbw-o-table"><tr class="vbw-o-table__row vbw-o-table__row--5">
        <td class="position">5</td><td><img src="/flag_jpn"><a href="/teams/women/123/schedule/">Japan</a></td></tr>
        <tr class="vbw-o-table__row vbw-o-table__row---9"><td class="position"></td>
        <td><img src="/flag_jpn"><a href="/teams/women/456/schedule/">Japan</a></td></tr></table>'''
        results = parse_volleyball_world_final_standings(html, 'women', 'https://official.example/standings')
        self.assertEqual([(item['externalTeamId'], item['rank']) for item in results], [(123, 5), (456, 9)])

if __name__ == '__main__': unittest.main()
