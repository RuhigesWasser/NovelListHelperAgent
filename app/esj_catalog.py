"""Keep author-defined ESJ groups; recommend numbered chapters, not link positions."""
import re
import unicodedata
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup,Tag


def chapter_number(title):
    text=unicodedata.normalize('NFKC',title).strip()
    match=re.match(r'^(?:第\s*)?([0-9]+|[一二三四五六七八九十百零〇两兩]+)\s*(?:章|话|話|回|節|节|[.、:：\-]|\s|$)',text)
    if not match:
        match=re.match(r'^(?:chapter\s+|episode\s+|no\.?\s*)(\d+)\b',text,re.I)
    if not match:return None
    number=match[1]
    if number.isdigit():return int(number)
    digits=dict(zip('零〇一二三四五六七八九两兩',(0,0,1,2,3,4,5,6,7,8,9,2,2)))
    if not any(c in number for c in '十百'):return int(''.join(str(digits[c]) for c in number))
    total,current=0,0
    for char in number:
        if char in digits:current=digits[char]
        else:
            total+=(current or 1)*({'十':10,'百':100}[char]);current=0
    return total+current


def parse(html,url,book_id):
    root=BeautifulSoup(html,'html.parser').select_one('#chapterList')
    if root is None:return []
    rows=[]
    def walk(node,groups):
        current=groups
        for child in node.children:
            if not isinstance(child,Tag):continue
            if child.name=='summary':continue
            if child.name=='details':
                summary=child.find('summary',recursive=False)
                walk(child,groups+([summary.get_text(' ',strip=True)] if summary else []))
            elif child.name in ('h2','h3','h4') or child.name=='p' and 'non' in child.get('class',[]):
                heading=child.get_text(' ',strip=True)
                if heading:current=groups+[heading]
            elif child.name=='a' and child.get('href'):
                target=urljoin(url,child['href']);parsed=urlsplit(target)
                if parsed.hostname!=urlsplit(url).hostname or not re.fullmatch(rf'/forum/{book_id}/\d+\.html',parsed.path):continue
                title=child.get_text(' ',strip=True)
                number=chapter_number(title)
                extra=bool(re.search(r'公告|通知|番外|随笔|隨筆|杂谈|雜談|插图|插圖|设定|設定|後記|后记|短文合集',' / '.join(current)))
                if number is None and re.match(r'^(公告|通知|译者|譯者|后记|後記|番外|趣看)',title):extra=True
                rows.append({'title':title,'url':target,'group':' / '.join(current) or '未分组',
                             'number':number,'kind':'附加内容' if extra else '编号章节' if number is not None else '未编号',
                             'order':len(rows)})
            else:walk(child,current)
    walk(root,[])
    unique={}
    for row in rows:
        old=unique.get(row['url'])
        if old is None or old['number'] is None and row['number'] is not None:unique[row['url']]=row
    return sorted(unique.values(),key=lambda row:row['order'])


def recommend(entries,limit=3):
    groups={}
    for row in entries:
        if row.get('kind')=='编号章节':groups.setdefault(row['group'],[]).append(row)
    candidates=[]
    for group,rows in groups.items():
        selected=[]
        for number in range(1,limit+1):
            matches=[r for r in rows if r['number']==number]
            if len(matches)!=1:break
            selected.append(matches[0])
        if len(selected)==limit:candidates.append((group,selected))
    if len(candidates)==1:
        group,selected=candidates[0]
        return selected,f'按章节编号推荐第 1—{limit} 章（{group}），请核对后获取。'
    if len(candidates)>1:return [],'多个分组都从第 1 章开始，请选择对应分组和章节。'
    return [],'未找到唯一、连续的第 1—3 章。目录可能包含公告、随笔或无编号章节，请手动选择。'
