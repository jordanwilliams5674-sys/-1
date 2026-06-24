from __future__ import annotations

import unittest

from beidou_us_radar.core.credibility_score import score_event_credibility, source_label
from beidou_us_radar.core.dashboard_bridge import candidate_events


class DashboardBridgeTest(unittest.TestCase):
    def test_news_url_does_not_become_official_anchor(self) -> None:
        events = candidate_events(
            {
                "生成时间UTC": "2026-06-06T12:00:00+00:00",
                "重要置顶": [
                    {
                        "股票代码": "MRVL",
                        "公司名称": "Marvell",
                        "事件标注": "AI infrastructure news",
                        "当前行情": {"当前涨跌幅": 2.1},
                        "催化来源": [
                            {
                                "中文标题": "Marvell AI news",
                                "来源": "Yahoo Finance RSS",
                                "发布时间": "2026-06-06T11:45:00+00:00",
                                "网址": "https://finance.yahoo.com/news/example",
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        event.credibility = score_event_credibility(event)
        self.assertEqual(event.source_kind, "reliable_news")
        self.assertEqual(event.official_url, "")
        self.assertEqual(source_label(event), "高可信新闻源")
        self.assertLess(event.credibility, 0.9)

    def test_sec_url_stays_official_anchor(self) -> None:
        events = candidate_events(
            {
                "生成时间UTC": "2026-06-06T12:00:00+00:00",
                "重要置顶": [
                    {
                        "股票代码": "MRVL",
                        "公司名称": "Marvell",
                        "事件标注": "8-K filing",
                        "催化来源": [
                            {
                                "中文标题": "Marvell files 8-K",
                                "来源": "SEC EDGAR",
                                "发布时间": "2026-06-06T11:45:00+00:00",
                                "网址": "https://www.sec.gov/Archives/example",
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        event.credibility = score_event_credibility(event)
        self.assertEqual(event.source_kind, "sec")
        self.assertIn("sec.gov", event.official_url)
        self.assertEqual(source_label(event), "官方/权威源")


if __name__ == "__main__":
    unittest.main()
