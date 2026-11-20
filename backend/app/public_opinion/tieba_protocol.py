"""Small stdlib-only Tieba contracts shared by the two Python environments."""
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit,parse_qs

ACCOUNT_URL='https://tieba.baidu.com/hottopic/browse/topicList'


def account_page(payload):
    if not isinstance(payload,dict) or payload.get('errno') not in {0,'0'}:return None
    rows=payload.get('data',{}).get('bang_topic',{}).get('topic_list',[])
    for row in rows[:10]:
        if not isinstance(row,dict):continue
        identifier=str(row.get('topic_id') or '')
        if identifier.isdigit():return 'https://tieba.baidu.com/hottopic/browse/hottopic?topic_id='+identifier
    return None


def post_id(url):
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname!='tieba.baidu.com' or p.port not in {None,443} or p.username or p.password:return None
        match=re.fullmatch(r'/p/(\d+)/?',p.path)
        return match[1] if match else None
    except ValueError:return None


def topic_url(url):
    try:
        p=urlsplit(url)
        return (p.scheme=='https' and p.hostname=='tieba.baidu.com' and p.port in {None,443}
                and not p.username and not p.password and p.path=='/hottopic/browse/hottopic'
                and len(parse_qs(p.query).get('topic_id',[]))==1 and parse_qs(p.query)['topic_id'][0].isdigit())
    except ValueError:return False


class Scripts(HTMLParser):
    def __init__(self):super().__init__();self.active=False;self.parts=[]
    def handle_starttag(self,tag,attrs):self.active=tag=='script' and not dict(attrs).get('src')
    def handle_endtag(self,tag):
        if tag=='script':self.active=False
    def handle_data(self,data):
        if self.active:self.parts.append(data)


def server_login(html):
    """Read literal top-level PageData.user fields, without executing JavaScript.

    An unrelated profile, local Cookie flag, or nested/quoted is_login cannot
    confirm a session. Call only on a fresh response from ACCOUNT_URL.
    """
    if not isinstance(html,str) or len(html)>2_000_000:return 'unverified'
    scripts=Scripts();scripts.feed(html)
    for script in scripts.parts:
        match=re.search(r'(?:^|[;\n])\s*PageData\.user\s*=\s*\{',script)
        if not match:continue
        fields={};start=match.end();depth=0;quote=None;escape=False
        for i in range(start,min(len(script),start+50000)):
            c=script[i]
            if quote:
                if escape:escape=False
                elif c=='\\':escape=True
                elif c==quote:quote=None
                continue
            if c in "\"'":quote=c;continue
            if c in '{[(':depth+=1;continue
            elif c in '}])':
                if c=='}' and depth==0:delimiter=True
                else:depth-=1;continue
            elif c==',' and depth==0:delimiter=True
            else:continue
            if delimiter:
                pair=script[start:i].split(':',1);start=i+1
                if len(pair)==2:
                    key=pair[0].strip().strip('\"\'')
                    if key in {'is_login','user_id','id'}:
                        value=pair[1].strip()
                        try:
                            literal=json.loads(value)
                            if isinstance(literal,(str,int,bool)):fields[key]=literal
                        except ValueError:pass
                        if re.fullmatch(r"'\d+'",value):fields[key]=value[1:-1]
                if c=='}':break
        flag=fields.get('is_login')
        if flag in {0,False}:return 'expired'
        identifier=str(fields.get('user_id') or fields.get('id') or '')
        if flag in {1,True} and identifier.isdigit() and int(identifier)>0:return 'verified'
    return 'unverified'
