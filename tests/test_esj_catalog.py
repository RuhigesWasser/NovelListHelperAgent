import unittest
from unittest.mock import patch
from app import esj_catalog,chapters,providers


def link(number,title):
    return f'<a href="/forum/123/{number}.html"><p>{title}</p></a>'


class ESJCatalogTests(unittest.TestCase):
    def test_translation_front_matter_is_not_first_chapter(self):
        html='<div id="chapterList">'+link(99,'术语表')+link(98,'来自作者的翻译许可')+link(97,'【有图】粉丝图')+'<p class="non">正篇</p>'+''.join(link(n,f'No.{n} 故事') for n in range(1,5))+'</div>'
        entries=esj_catalog.parse(html,'https://www.esjzone.one/detail/123.html','123')
        selected,note=esj_catalog.recommend(entries)
        self.assertEqual([e['number'] for e in selected],[1,2,3])
        self.assertEqual([e['group'] for e in selected],['正篇']*3)
        self.assertIn('正篇',note)

    def test_pinned_link_duplicate_and_descending_order(self):
        html='<div id="chapterList">'+link(3,'最新更新')+'<details><summary>正文</summary>'+''.join(link(n,f'第{n}章 内容') for n in [3,2,1])+'</details></div>'
        entries=esj_catalog.parse(html,'https://www.esjzone.one/detail/123.html','123')
        self.assertEqual(len(entries),3)
        self.assertEqual([e['number'] for e in esj_catalog.recommend(entries)[0]],[1,2,3])

    def test_unordered_diary_and_restarting_volumes_require_selection(self):
        html='<div id="chapterList">'+link(1,'本日')+link(2,'身体健康')+link(3,'完了')+'</div>'
        rows=esj_catalog.parse(html,'https://www.esjzone.one/detail/123.html','123')
        self.assertEqual(esj_catalog.recommend(rows)[0],[])
        rows=[{'group':g,'kind':'编号章节','number':n,'url':f'{g}/{n}'} for g in ['第一卷','第二卷'] for n in [1,2,3]]
        self.assertEqual(esj_catalog.recommend(rows)[0],[])

    def test_chinese_fullwidth_and_english_numbers(self):
        for text,number in [('第一章 初遇',1),('第２話 帰路',2),('Chapter 3 Test',3),('No.12 现况',12),('二〇二三 公告',2023),('第十二章 测试',12),('小说名3',None)]:
            self.assertEqual(esj_catalog.chapter_number(text),number,text)

    def test_unknown_catalog_never_silently_downloads_top_three(self):
        rows=[{'title':'公告','url':'one','group':'未分组','kind':'未编号','number':None}]
        with patch('app.chapters.catalog',return_value=('esj',rows)),patch('app.chapters.read_chapter',return_value={'content':'正文'}) as read:
            with self.assertRaises(providers.ProviderError):chapters.preview('book')
            read.assert_not_called()
            self.assertEqual(len(chapters.preview('book',selected_urls=['one'])['chapters']),1)
            with self.assertRaises(providers.ProviderError):chapters.preview('book',selected_urls=['https://other.example'])
