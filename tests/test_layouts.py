import unittest
from unittest.mock import patch
from app import organize,image_books


def row(text,x,y,w=180,h=25):
    return {'text':text,'box':[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],'score':.95}


class LayoutTests(unittest.TestCase):
    def extract(self,boxes):
        text='\n'.join(r['text'] for r in boxes)
        return organize.extract([{'text':'','images':[text]}],[8],layouts={'0:0':{'layout':boxes}})['items']

    def test_qidian_cover_words_are_not_book_heading_or_author(self):
        boxes=[row('真正的书名',300,20),row('封面文字',20,30),row('第二行',300,55),
               row('真正作者',300,100),row('作者：封面误读',20,110),row('奇幻·剑与魔法',300,145),
               row('123人正在投资瓜分收益',300,185),row('出圈指数',600,250)]
        book=self.extract(boxes)[0]
        self.assertEqual((book['title'],book['author'],book['platform']),('真正的书名第二行','真正作者','qidian'))

    def test_sfacg_cover_text_does_not_replace_author(self):
        for metadata in ('校园','连载中|校园|24万字'):
            boxes=[row('跨行标题',20,10),row('结束！',20,45),row('VIP',160,45),row(metadata,20,90),
                   row('封面上的书名',650,130),row('实际作者',90,170),row('封面文字',650,200),
                   row('14万字',20,300),row('月票',350,300),row('点赞',720,300)]
            book=self.extract(boxes)[0]
            self.assertEqual((book['title'],book['author']),('跨行标题结束！','实际作者'))

    def test_fanqie_cover_duplicates_and_separate_author_card(self):
        boxes=[row('封面识别错字',20,30),row('真正的标题',300,30),row('标题第二行',300,70),
               row('动漫衍生·连载中·1...',300,130),row('番茄原创',300,175),row('实际作者',90,300),
               row('作家Lv.1',330,301),row('暂无评分',20,400),row('潜力好书',650,400)]
        book=self.extract(boxes)[0]
        self.assertEqual((book['title'],book['author'],book['platform']),('真正的标题标题第二行','实际作者','fanqie'))

    def test_author_disagreement_retains_both_queries_until_verified(self):
        local={'title':'书名','author':'OCR错字','platform':'sfacg','floor_index':0,'image_index':0,'state':'draft'}
        vision={**local,'author':'正确作者'};plan={'items':[local],'skipped':[]}
        image_books.merge(plan,[vision],0,0)
        confirmed={**vision,'state':'verified','book':{'url':'https://book.sfacg.com/novel/123/'}}
        with patch('app.organize.verify_query',side_effect=[{'state':'review'},confirmed]):
            self.assertEqual(organize.verify(local)['author'],'正确作者')

    def test_cropped_title_requires_review_even_if_search_returns_a_match(self):
        item={'title':'半截标题','author':'作者','platform':'all','title_complete':False}
        with patch('app.organize.verify_query',return_value={**item,'state':'verified','book':{'url':'https://example.test/book'}}):
            result=organize.verify(item)
        self.assertEqual(result['state'],'review');self.assertIsNone(result['book'])

    def test_library_popup_title_and_author_update_row(self):
        text='真实书名\n继续阅读\n真实作者·1小时前更新\n读到1章\n已加入书架\n去详情'
        result=organize.extract([{'text':'','images':[text]}],[1])
        self.assertEqual((result['items'][0]['title'],result['items'][0]['author']),('真实书名','真实作者'))

    def test_watermark_corrupted_title_becomes_an_alternative_not_an_extra_book(self):
        local={'title':'水印混入后完全不同的文字','author':'同一作者','platform':'fanqie','floor_index':0,'image_index':0,'state':'draft'}
        corrected={**local,'title':'清晰封面上的真实书名'}
        plan={'items':[local],'skipped':[]};image_books.merge(plan,[corrected],0,0)
        self.assertEqual(len(plan['items']),1)
        self.assertEqual(local['alternative_titles'],[corrected['title']])
