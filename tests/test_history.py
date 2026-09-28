import unittest
from unittest.mock import MagicMock, patch
from scripts.history import parse_jbv_rankings, parse_results


class HistoryTests(unittest.TestCase):
    def parse(self, rows, corrections=None, title='JAPAN BEACH VOLLEYBALL TOUR 2026\n試合結果順位【女子】'):
        page = MagicMock()
        page.extract_text.return_value = title
        page.extract_tables.return_value = [[
            ['順位', 'Player１', None, None, 'Player２', None, None, 'Total Point'],
            [None, '氏名', '所属', 'Point', '氏名', '所属', 'Point', None],
            *[[rank, a, '所属', None, b, '所属', None, None] for rank, a, b in rows],
        ]]
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = [page]
        with patch('scripts.history.pdfplumber.open', return_value=pdf):
            return parse_results(b'', 2026, corrections)

    def test_merged_final_ranks_are_preserved(self):
        teams = self.parse([('優勝', '甲', '乙'), ('3位', '丙', '丁'), (None, '戊', '己')])
        self.assertEqual([e['rank'] for e in teams], [1, 3, 3])
        self.assertEqual(teams[-1]['names'], ['戊', '己'])
        self.assertTrue(all(e['status'] == 'completed' for e in teams))

    def test_blank_does_not_inherit_previous_rank(self):
        with self.assertRaises(ValueError):
            self.parse([('準優勝', '甲', '乙'), ('', '丙', '丁')])

    def test_reviewed_correction_checks_original_cell(self):
        fix = {'1:丙': {'expected': '', 'label': '3位'}}
        teams = self.parse([('準優勝', '甲', '乙'), ('', '丙', '丁')], fix)
        self.assertEqual(teams[-1]['rank'], 3)
        with self.assertRaises(ValueError):
            self.parse([('準優勝', '甲', '乙'), ('5位', '丙', '丁')], fix)

    def test_pool_rank_is_not_final_result(self):
        with self.assertRaises(ValueError):
            self.parse([('1', '甲', '乙')], title='TOUR 2026 プール戦 試合結果【女子】')

    def test_other_year_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse([('優勝', '甲', '乙')], title='TOUR 2025 試合結果順位【女子】')

    @patch('scripts.history.pdfplumber.open')
    def test_jbv_final_ranking_table_is_explicitly_parsed(self, opened):
        page = MagicMock()
        page.extract_text.return_value = '最終順位\n男子'
        page.extract_tables.return_value = [[
            ['順位', '氏 名（所 属）', None, None, 'ポイント', None],
            ['1位', '安達\n今井', '龍一\n駿世', '所属', '320\n320', '640'],
            ['３位', '松下\nMartin', '道一\nKaufer', '所属', '213\n213', '426'],
            [None, '坂東\n山口', '巧望\n和也', '所属', '213\n213', '426'],
        ]]
        opened.return_value.__enter__.return_value.pages = [page]
        teams = parse_jbv_rankings(b'', 'men')
        self.assertEqual([team['rank'] for team in teams], [1, 3, 3])
        self.assertEqual(teams[1]['names'], ['松下 道一', 'Martin Kaufer'])
