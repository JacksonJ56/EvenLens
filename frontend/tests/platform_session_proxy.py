"""Real Next.js proxy checks. Uses a removed platform: no login or paid tasks."""
import argparse
import json
from urllib.parse import urlsplit,urlunsplit
from urllib.request import Request,urlopen
from urllib.error import HTTPError


def run(base):
    parsed=urlsplit(base)
    def request(host,origin,site):
        url=urlunsplit((parsed.scheme,host+(':'+str(parsed.port) if parsed.port else ''),
            '/api/public-opinion/sessions/douyin/check','',''))
        req=Request(url,data=b'',method='POST',headers={'Origin':origin,'Sec-Fetch-Site':site})
        try:
            with urlopen(req,timeout=15) as response:return response.status,json.load(response)
        except HTTPError as error:return error.code,json.load(error)
    for host in ['127.0.0.1','localhost']:
        origin=f'{parsed.scheme}://{host}'+(':'+str(parsed.port) if parsed.port else '')
        status,body=request(host,origin,'same-origin')
        assert status==422 and '暂不支持' in body['detail'],(host,status,body)
    own=f'{parsed.scheme}://127.0.0.1'+(':'+str(parsed.port) if parsed.port else '')
    for origin,site in [('https://evil.example','cross-site'),(own,'cross-site'),
                        (own.replace('127.0.0.1','localhost'),'same-site')]:
        status,_=request('127.0.0.1',origin,site)
        assert status==403,(origin,site,status)
    print(json.dumps({'real_proxy':'passed','same_origin_loopback_hosts':2,'rejected_origins':3,'login_windows':0,'agent_tasks':0}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://127.0.0.1:3000')
    run(parser.parse_args().base)
