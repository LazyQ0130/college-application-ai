#!/usr/bin/env python3
"""雪峰志愿分析助手 — 单文件服务器：HTML UI + API + 数据库查询"""
import os, re, json, sqlite3, gzip, shutil, urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, 'admission_clean.db')
GZ_PATH = os.path.join(HERE, 'admission_clean.db.gz')
if not os.path.exists(DB_PATH) and os.path.exists(GZ_PATH):
    with gzip.open(GZ_PATH, 'rb') as gz:
        with open(DB_PATH, 'wb') as f:
            shutil.copyfileobj(gz, f)

HAS_DB = os.path.exists(DB_PATH)

PROVINCES = ['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽',
             '福建','江西','山东','河南','湖北','湖南','广东','广西','海南','四川','贵州','云南',
             '西藏','陕西','甘肃','青海','宁夏','新疆','内蒙古']

def query_db(province=None, school=None, major=None, limit=50):
    if not HAS_DB: return None
    conn = sqlite3.connect(DB_PATH)
    conds, params = [], []
    if province: conds.append("province LIKE ?"); params.append(f"%{province}%")
    if school: conds.append("school LIKE ?"); params.append(f"%{school}%")
    if major: conds.append("major LIKE ?"); params.append(f"%{major}%")
    if not conds: conn.close(); return None
    sql = f"SELECT province,year,school_name,major_name,score,rank FROM admission WHERE {' AND '.join(conds)} AND rank>100 ORDER BY year DESC,rank ASC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [{'province':r[0],'year':r[1],'school_name':r[2],'major_name':r[3],'score':r[4],'rank':r[5]} for r in rows]

def web_search(query, n=5):
    # Baidu scraping no longer works (blocked). Return hint to use Tavily.
    return ["搜索无结果。请在前端API设置中填入Tavily Key以启用联网搜索（tavily.com免费注册）。"]

class Handler(BaseHTTPRequestHandler):
    def _send(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type','application/json;charset=utf-8')
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma','no-cache')
        self.send_header('Expires','0')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','*')
        self.end_headers()

    def do_GET(self):
        if self.path == '/ping':
            return self._send({'ok':True,'db':HAS_DB})
        if self.path.startswith('/query'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rows = query_db(qs.get('province',[''])[0], qs.get('school',[''])[0], qs.get('major',[''])[0])
            return self._send({'db':rows,'count':len(rows) if rows else 0})
        if self.path.startswith('/recommend'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            prov = qs.get('province',[''])[0]
            major = qs.get('major',[''])[0]
            keyword = qs.get('keyword',[''])[0]
            try: rank = int(qs.get('rank',['0'])[0])
            except: rank = 0
            try: score = int(qs.get('score',['0'])[0])
            except: score = 0
            print(f"[RECOMMEND] prov={prov} rank={rank} score={score} kw={keyword[:30] if keyword else 'none'}")
            if prov and (rank > 0 or score > 0):
                conn = sqlite3.connect(DB_PATH)
                base = "province LIKE ? AND (score>0 OR rank>0)"
                bp = [f'%{prov}%']
                if major: base += " AND major_name LIKE ?"; bp.append(f'%{major}%')
                if keyword:
                    kws = keyword.split(',')
                    kw_conds = []
                    for kw in kws:
                        kw_conds.append("(major_name LIKE ? OR school_name LIKE ?)")
                        bp.append(f'%{kw}%'); bp.append(f'%{kw}%')
                    base += " AND (" + " OR ".join(kw_conds) + ")"

                chong = []; wen = []; bao = []

                # Try rank-based first, fall back to score-based
                if rank > 0:
                    chong = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND rank>0 AND rank<? AND rank>=? ORDER BY rank ASC LIMIT 50",
                        bp+[rank, max(1,int(rank*0.85))]).fetchall()]
                    wen = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND rank>0 AND rank>=? AND rank<=? ORDER BY rank ASC LIMIT 50",
                        bp+[rank, int(rank*1.3)]).fetchall()]
                    bao = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND rank>0 AND rank>? AND rank<=? ORDER BY rank ASC LIMIT 50",
                        bp+[int(rank*1.3), int(rank*1.6)]).fetchall()]

                # If no results with keyword, retry without keyword (broader search)
                if not (chong or wen or bao) and keyword:
                    chong = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE province LIKE ? AND rank>0 AND rank<? AND rank>=? ORDER BY rank ASC LIMIT 50",
                        [f'%{prov}%', rank, max(1,int(rank*0.85))]).fetchall()]
                    wen = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE province LIKE ? AND rank>0 AND rank>=? AND rank<=? ORDER BY rank ASC LIMIT 50",
                        [f'%{prov}%', rank, int(rank*1.3)]).fetchall()]
                    bao = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE province LIKE ? AND rank>0 AND rank>? AND rank<=? ORDER BY rank ASC LIMIT 50",
                        [f'%{prov}%', int(rank*1.3), int(rank*1.6)]).fetchall()]

                # If rank query returned nothing, try score-based
                if not (chong or wen or bao) and score > 0:
                    # First try with keyword
                    chong = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND score>? AND score<=? ORDER BY score DESC LIMIT 80",
                        bp+[score, score+35]).fetchall()]
                    wen = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND score>=? AND score<=? ORDER BY score ASC LIMIT 50",
                        bp+[score-25, score+35]).fetchall()]
                    bao = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                        conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base} AND score>=? AND score<? ORDER BY score ASC LIMIT 50",
                        bp+[score-50, score-25]).fetchall()]
                    # If keyword filtered everything, retry without keyword
                    if not (chong or wen or bao):
                        base2 = "province LIKE ? AND score>0"
                        bp2 = [f'%{prov}%']
                        chong = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                            conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base2} AND score>? AND score<=? ORDER BY score DESC LIMIT 80",
                            bp2+[score, score+40]).fetchall()]
                        wen = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                            conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base2} AND score>=? AND score<=? ORDER BY score ASC LIMIT 50",
                            bp2+[score-15, score+15]).fetchall()]
                        bao = [{'school':r[0],'major':r[1],'score':r[2],'rank':r[3],'year':r[4]} for r in
                            conn.execute(f"SELECT school_name,major_name,score,rank,year FROM admission WHERE {base2} AND score>=? AND score<? ORDER BY score ASC LIMIT 50",
                            bp2+[score-40, score-15]).fetchall()]
                conn.close()
                return self._send({'rank':rank,'score':score,'chong':chong,'wen':wen,'bao':bao})
            return self._send({'error':'need province and rank or score'},400)
        if self.path.startswith('/search'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = qs.get('q',[''])[0]
            if q: return self._send({'results':web_search(q)})
            return self._send({'results':[]})

        # Serve image files
        for img in ['img_suit.png']:
            if self.path == '/'+img:
                ip = os.path.join(HERE, img)
                if os.path.exists(ip):
                    self.send_response(200)
                    self.send_header('Content-Type','image/png')
                    self.send_header('Cache-Control','max-age=3600')
                    self.end_headers()
                    with open(ip,'rb') as f: self.wfile.write(f.read())
                    return

        # Serve the main UI page
        self.send_response(200)
        self.send_header('Content-Type','text/html;charset=utf-8')
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma','no-cache')
        self.send_header('Expires','0')
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode('utf-8'))

    def log_message(self, format, *args):
        msg = format%args if args else format
        if '/recommend' in msg or '/query' in msg or '/ping' in msg or '/search' in msg:
            print(f"[REQ] {msg}")

# ========== 完整的 HTML 页面（内嵌 JS）==========
HTML_PAGE = r'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><meta name="description" content="基于24省官方录取数据与公开志愿填报方法论的高考志愿分析工具"><title>雪峰志愿分析助手｜高考志愿数据分析工具</title>
<style>:root{--bg:#f7f6f2;--side:#eeebe2;--card:#fff;--bdr:#d8d3c7;--txt:#1c1b19;--t2:#716e67;--red:#c63f35;--red-soft:#f9ebe8;--gold:#9a6a20;--green:#22863a;--shadow:0 14px 40px rgba(54,43,31,.08)}
.dark{--bg:#191918;--side:#23221f;--card:#2b2a27;--bdr:#49463f;--txt:#eeeae3;--t2:#aaa59c;--red:#e05b50;--red-soft:#3b2926;--gold:#d6a85e;--shadow:0 14px 40px rgba(0,0,0,.22)}
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px/1.7 'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--txt);height:100vh;display:flex}
.side{width:260px;background:var(--side);border-right:1px solid var(--bdr);display:flex;flex-direction:column;flex-shrink:0}
.side h2{padding:20px 18px 4px;font-size:17px;line-height:1.35}.side .sub{font-size:11px;color:var(--t2);padding:0 18px 16px;border-bottom:1px solid var(--bdr)}
.list{overflow-y:auto;padding:4px 12px;flex:1;min-height:60px}
.item{padding:10px 12px;border-radius:6px;cursor:pointer;font-size:13px;color:var(--t2);margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item:hover{background:var(--card)}.item.on{background:var(--red);color:#fff}
.new-btn{margin:8px 12px 16px;padding:8px;text-align:center;border:1px dashed var(--bdr);border-radius:6px;cursor:pointer;font-size:12px;color:var(--t2)}
.new-btn:hover{background:var(--card)}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.bar{min-height:60px;display:flex;align-items:center;padding:8px 20px;border-bottom:1px solid var(--bdr);gap:10px;background:var(--side)}
.bar .logo{font-weight:700;font-size:17px;margin-right:auto}
.bar button{padding:6px 12px;border:1px solid var(--bdr);border-radius:6px;background:var(--card);cursor:pointer;font-size:12px;color:var(--txt)}
.bar button.on{background:var(--red);color:#fff;border-color:var(--red)}.bar .api-btn{background:var(--red);color:#fff;border-color:var(--red)}
.bar img{width:40px;height:40px;border-radius:50%;object-fit:cover;border:2px solid var(--bdr)}
.msgs{flex:1;overflow-y:auto;padding:24px 40px}
.welcome{max-width:1060px;margin:0 auto;color:var(--txt)}
.hero{position:relative;overflow:hidden;padding:34px;border:1px solid var(--bdr);border-radius:18px;background:linear-gradient(135deg,var(--card) 0%,var(--red-soft) 100%);box-shadow:var(--shadow)}
.hero::after{content:'24省';position:absolute;right:24px;top:6px;font-size:86px;font-weight:900;line-height:1;color:var(--red);opacity:.06;pointer-events:none}
.eyebrow{display:inline-flex;align-items:center;gap:8px;padding:5px 10px;border-radius:999px;background:var(--red-soft);color:var(--red);font-size:12px;font-weight:700;letter-spacing:.04em}
.hero h1{margin-top:14px;font-size:36px;line-height:1.2;letter-spacing:-.03em}.hero .lead{margin-top:10px;font-size:18px;line-height:1.6;font-weight:650;max-width:820px}
.hero .desc{margin-top:16px;max-width:900px;color:var(--t2);font-size:14px;line-height:1.9}
.hero .desc strong{color:var(--txt)}.trust-line{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.trust-line span{padding:6px 10px;border:1px solid var(--bdr);border-radius:8px;background:var(--card);font-size:12px;color:var(--t2)}
.feature-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:14px}
.feature{padding:18px;border:1px solid var(--bdr);border-radius:14px;background:var(--card);box-shadow:0 8px 24px rgba(54,43,31,.04)}
.feature .num{font-size:11px;color:var(--red);font-weight:800;letter-spacing:.12em}.feature h3{margin-top:7px;font-size:16px}.feature p{margin-top:7px;color:var(--t2);font-size:12px;line-height:1.75}
.starter{margin-top:14px;padding:18px;border:1px solid var(--bdr);border-radius:14px;background:var(--card)}
.starter-title{font-weight:700}.starter-sub{margin-top:3px;color:var(--t2);font-size:12px}
.examples{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.example-btn{padding:7px 11px;border:1px solid var(--bdr);border-radius:999px;background:var(--bg);color:var(--txt);font-size:12px;cursor:pointer}.example-btn:hover{border-color:var(--red);color:var(--red);background:var(--red-soft)}
.notice{margin-top:14px;padding:12px 14px;border-left:3px solid var(--gold);border-radius:8px;background:var(--card);color:var(--t2);font-size:11px;line-height:1.7}
.bubble{max-width:75%;padding:12px 16px;border-radius:10px;margin-bottom:10px;font-size:13px;line-height:1.7;white-space:pre-wrap;word-break:break-word}
.bubble.u{background:var(--red);color:#fff;margin-left:auto}.bubble.a{background:var(--side);border:1px solid var(--bdr)}
.bubble .who{font-size:10px;opacity:.6;margin-bottom:4px}
.composer{padding:10px 20px 16px;background:linear-gradient(180deg,transparent,var(--bg) 22%)}
.input-tip{max-width:1060px;margin:0 auto 7px;color:var(--t2);font-size:11px}
.inp{max-width:1060px;margin:0 auto;display:flex;gap:8px}
.inp textarea{flex:1;padding:13px 14px;border:1px solid var(--bdr);border-radius:10px;font:inherit;resize:none;height:54px;background:var(--card);color:var(--txt);outline:none;box-shadow:0 5px 18px rgba(54,43,31,.04)}
.inp textarea:focus{border-color:var(--red);box-shadow:0 0 0 3px var(--red-soft)}.inp button{padding:0 24px;background:var(--red);color:#fff;border:none;border-radius:10px;cursor:pointer;font-weight:700}
.footer-disclaimer{max-width:1060px;margin:7px auto 0;text-align:center;color:var(--t2);font-size:10px;line-height:1.5}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:99;display:none;align-items:center;justify-content:center}
.overlay>div{background:var(--card);border-radius:12px;padding:28px;width:460px;border:1px solid var(--bdr)}
.overlay h3{margin-bottom:16px}.overlay label{display:block;font-size:11px;color:var(--t2);margin:12px 0 4px}
.label-row{display:flex;align-items:center;gap:6px;margin:12px 0 4px}.label-row label{margin:0}
.api-help{position:relative;display:inline-flex}
.api-help-btn{width:17px;height:17px;padding:0;border:1px solid #9a9a9a!important;border-radius:50%;background:#eee!important;color:#777!important;font-family:inherit;font-size:11px;font-weight:700;line-height:15px;cursor:pointer;text-align:center}
.api-help-btn:hover,.api-help-btn:focus{outline:none;border-color:#666!important;background:#e2e2e2!important;color:#555!important;box-shadow:0 0 0 3px rgba(128,128,128,.14)}
.api-help-pop{position:absolute;left:24px;top:-12px;z-index:3;width:300px;padding:12px 14px;border:1px solid var(--bdr);border-radius:10px;background:var(--card);box-shadow:var(--shadow);color:var(--txt);font-size:12px;line-height:1.7;opacity:0;visibility:hidden;transform:translateY(4px);transition:.16s ease;pointer-events:none}
.api-help-pop::before{content:'';position:absolute;left:-6px;top:15px;width:10px;height:10px;background:var(--card);border-left:1px solid var(--bdr);border-bottom:1px solid var(--bdr);transform:rotate(45deg)}
.api-help-pop ol{margin:0;padding-left:18px}.api-help-pop li+li{margin-top:5px}.api-help-pop a{color:var(--red);font-weight:700}
.api-help:hover .api-help-pop,.api-help:focus-within .api-help-pop,.api-help.open .api-help-pop{opacity:1;visibility:visible;transform:translateY(0);pointer-events:auto}
.overlay input{width:100%;padding:10px;border:1px solid var(--bdr);border-radius:6px;font:inherit;background:var(--bg);color:var(--txt)}
.overlay .btns{display:flex;gap:8px;margin-top:20px}.overlay .btns button{padding:10px 20px;border:1px solid var(--bdr);border-radius:6px;cursor:pointer}.overlay .btns .ok{flex:1;background:var(--red);color:#fff}
.st{font-size:12px;margin-top:10px}.st.g{color:var(--green)}.st.b{color:var(--red)}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--t2);animation:dot 1.4s infinite;margin:0 2px}
.dot:nth-child(2){animation-delay:.2s}.dot:nth-child(3){animation-delay:.4s}
@keyframes dot{0%,80%,100%{transform:scale(.6)}40%{transform:scale(1)}}
.bubble{position:relative;z-index:1}.welcome{position:relative;z-index:1}
@media(max-width:1080px){.feature-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.hero h1{font-size:31px}.msgs{padding:20px 24px}}
@media(max-width:760px){body{height:100dvh}.side{display:none}.bar{padding:8px 12px;flex-wrap:wrap}.bar .logo{width:100%;font-size:15px}.bar img{width:34px;height:34px}.msgs{padding:14px 12px}.hero{padding:23px 19px}.hero h1{font-size:28px}.hero .lead{font-size:16px}.feature-grid{grid-template-columns:1fr}.composer{padding:8px 12px 12px}.inp button{padding:0 17px}.bubble{max-width:90%}.overlay>div{width:calc(100% - 24px);padding:22px}.api-help-pop{position:fixed;left:12px;right:12px;top:86px;width:auto}.api-help-pop::before{display:none}}
</style></head><body>
<div class="side"><h2>雪峰志愿分析助手</h2><div class="sub">录取数据 × 志愿方法论</div>
<div class="list" id="chatList"></div><div class="new-btn" id="newBtn">+ 新建对话</div></div>
<div class="main"><div class="bar"><span class="logo">雪峰志愿分析助手</span>
<img id="avt" src="/img_suit.png"><button id="themeBtn">🌓</button><button class="api-btn" id="apiBtn">API设置</button></div>
<div class="msgs" id="msgArea"></div>
<div class="composer"><div class="input-tip">输入你的省份、分数、位次、选科和想学方向，我帮你先做一版志愿初筛。</div><div class="inp"><textarea id="inp" aria-label="志愿分析问题" placeholder="例如：江苏物理类 590 分，位次 3.2 万，想学计算机，怎么填？"></textarea><button id="sendBtn">开始分析</button></div><div class="footer-disclaimer">分析结果仅作初步参考，最终请以本省教育考试院、学校招生章程和正式志愿填报系统为准。</div></div></div>
<div class="overlay" id="setOverlay"><div><h3>API设置</h3>
<label>Base URL</label><input id="sUrl" placeholder="https://api.deepseek.com">
<div class="label-row"><label for="sKey">API Key</label><div class="api-help" id="apiKeyHelp"><button type="button" class="api-help-btn" id="apiKeyHelpBtn" aria-label="查看 DeepSeek API Key 获取说明" aria-expanded="false" aria-controls="apiKeyHelpPop">!</button><div class="api-help-pop" id="apiKeyHelpPop" role="tooltip"><ol><li>打开 <a href="https://platform.deepseek.com" target="_blank" rel="noopener">platform.deepseek.com</a>，注册并登录。</li><li>左侧点击 <strong>API Keys</strong> → 创建 → 复制 <strong>sk-</strong> 开头的密钥。密钥只显示一次，请妥善保存。</li></ol></div></div></div><input type="password" id="sKey" placeholder="sk-...">
<label>Model</label><input id="sModel" placeholder="deepseek-chat">
<label>Tavily Key <span style="color:var(--red);font-size:11px;font-weight:600">(选填，建议配置)</span></label><input type="password" id="sTav" placeholder="tvly-..."><div style="background:var(--side);border-radius:6px;padding:8px 10px;margin:4px 0 8px;font-size:11px;line-height:1.6;color:var(--txt)"><b>做什么的？</b> 用于联网检索最新分数线、学校招生信息和行业趋势，帮助补充本地数据库。<br><b>为什么建议配置？</b> 招生计划和政策每年会变化，联网结果可用于交叉核验，但仍应以考试院和学校官网为准。<br><b>怎么获取？</b> 打开 <a href="https://tavily.com" target="_blank" rel="noopener" style="color:var(--red);font-weight:600">tavily.com</a> → 注册账号 → 复制 tvly- 开头的 Key → 粘贴到这里。<br><b>不填可以吗？</b> 可以，本地录取数据库和基础聊天功能仍然可用。</div>
<div class="btns"><button id="closeSetBtn">取消</button><button class="ok" id="testBtn">保存并测试</button></div><div class="st" id="st"></div></div></div>
<script>
var chats,curId;try{chats=JSON.parse(localStorage.getItem('xf_chats')||'{}');}catch(e){chats={};localStorage.removeItem('xf_chats');}curId=localStorage.getItem('xf_cur')||'';
var PG=[
"你是“雪峰志愿分析助手”的高考志愿分析顾问。你的表达直白、务实、就业导向，可参考张雪峰式的公开志愿填报方法论，但你不是张雪峰本人，也不代表任何真人或机构，不得声称官方授权、亲自指导或保证录取。",
"",
"【核心规则】",
"1. 位次优先：先看省份、选科和位次，再看裸分。引用数据必须写清省份、年份、分数、位次和来源。",
"2. 省份志愿政策感知：专业+院校模式（浙江80/山东96/河北96/重庆96/辽宁112）；院校+专业组模式（江苏40/广东45/湖北45/湖南45/福建40/北京30/天津50/上海24/海南24/河南48/四川45/陕西45/山西45/云南40/贵州45/内蒙古45/安徽45/江西45/黑龙江40/吉林40/广西40/甘肃45/新疆45/宁夏45/青海45/西藏45）。政策可能调整，必须提醒以当年省考试院文件为准。",
"3. 冲稳保是风险分层，不是录取承诺。默认思路可按冲20%、稳50%、保30%，但应根据用户风险偏好调整，保底至少给出明确思路。",
"4. 用户提供的省份、分数、位次、选科和家庭情况默认按其描述分析，不无端质疑。",
"5. 数据铁律：[真实录取数据]优先使用；[联网搜索]必须标注“据网上公开信息，仅供参考”；两个来源都没有的数据不得编造。不得使用“稳录、保证录取、绝不滑档、100%准确”等承诺。",
"6. 专业建议必须结合兴趣、学习难度、家庭资源、就业目标、考研考公意向、行业门槛与城市产业。不要把任何专业简单绝对化为“必报”或“绝对不能报”，要解释适用条件和代价。",
"7. 用户明确想学或排斥的方向要严格尊重；数据库混入不相关专业时必须过滤。专业对口优先于只追学校名气。",
"",
"【默认回答结构】",
"高考志愿相关问题默认使用以下五个清晰标题，信息不足时也先给当前能判断的内容，不要只追问：",
"一、定位判断",
"根据省份、分数、位次、选科判断大概层次，明确说明位次通常比裸分更重要；数据不足时说明判断边界。",
"二、专业建议",
"结合兴趣、家庭资源、就业目标、考研考公意向，分别说明适合、谨慎和不适合的专业方向及理由。",
"三、冲稳保方向",
"分别解释“冲、稳、保”的筛选逻辑和风险，不要只堆学校名。若有真实数据，逐条注明年份与来源；没有数据就只给方向，不编数字。",
"四、风险提醒",
"至少检查专业调剂、院校专业组、选科限制、城市取舍、热门专业虚火、招生计划及数据年份变化。",
"五、下一步建议",
"信息不全时，从省份、分数、位次、选科、目标城市、专业偏好、家庭资源、就业/升学目标、是否接受调剂、学费范围中，只追问最关键的1至2项，并给用户可直接复制的补充模板。",
"",
"重要：不要只给结论，要解释为什么这样分。不要冒充真人，不做录取承诺。结尾提醒：本分析仅供志愿初筛，最终以本省教育考试院、学校招生章程和正式志愿填报系统为准。"
].join("\n");
function S(id){return document.getElementById(id);}
function welcomeHTML(){
  return '<div class="welcome">'+
    '<section class="hero"><span class="eyebrow">高考志愿初筛工具</span><h1>雪峰志愿分析助手</h1>'+
    '<p class="lead">不是只会聊天的 AI，而是会查数据、会盘专业、会拆冲稳保的高考志愿分析工具。</p>'+
    '<p class="desc">它内置 <strong>24 省官方录取数据库</strong>，会结合省份、分数、位次、选科和专业偏好，真正去查数据、盘志愿、拆风险。系统方法论整理自<strong>张雪峰八本志愿填报专著 + 61 节专业视频课程（1500+ 分钟）</strong>，把“张雪峰那套”就业导向、专业优先、家庭资源、城市取舍和冲稳保逻辑塞进 AI。你把自己的情况说清楚，它先帮你筛掉明显不合适的选择，再讲清能冲什么、该稳什么、必须保什么。</p>'+
    '<div class="trust-line"><span>24 省录取数据</span><span>位次优先分析</span><span>专业与就业拆解</span><span>保留联网核验能力</span></div></section>'+
    '<section class="feature-grid"><article class="feature"><div class="num">01 / DATA</div><h3>会查数据</h3><p>内置 24 省官方录取数据库，优先结合历年录取线、位次和院校信息进行分析，不只凭感觉推荐。</p></article>'+
    '<article class="feature"><div class="num">02 / MAJOR</div><h3>会盘专业</h3><p>从就业前景、学习难度、家庭资源、考研考公、行业门槛等角度，判断一个专业到底适不适合你。</p></article>'+
    '<article class="feature"><div class="num">03 / RISK</div><h3>会拆冲稳保</h3><p>根据分数、位次和目标方向，把志愿拆成“冲一冲、稳一稳、保一保”，并提醒调剂和滑档风险。</p></article>'+
    '<article class="feature"><div class="num">04 / STYLE</div><h3>说话够直白</h3><p>参考张雪峰式表达风格，不绕弯子，不只说好听话，重点讲现实选择、专业坑位和就业落点。</p></article></section>'+
    '<section class="starter"><div class="starter-title">不知道怎么问？点一个例子直接开始</div><div class="starter-sub">信息越完整，初筛越有参考价值。位次通常比分数更关键。</div><div class="examples">'+
    '<button class="example-btn" data-example="江苏物理类 590 分，想学计算机，怎么填？">江苏物理类 590 分，想学计算机，怎么填？</button>'+
    '<button class="example-btn" data-example="普通家庭，想选就业稳一点的专业">普通家庭，想选就业稳一点的专业</button>'+
    '<button class="example-btn" data-example="我这个分数能不能冲 211？">我这个分数能不能冲 211？</button>'+
    '<button class="example-btn" data-example="电气、计算机、电子信息怎么选？">电气、计算机、电子信息怎么选？</button>'+
    '<button class="example-btn" data-example="哪些专业看着热门但不建议乱报？">哪些专业看着热门但不建议乱报？</button></div></section>'+
    '<div class="notice"><strong>说明：</strong>本工具参考公开志愿填报方法论和数据资料进行分析，不代表任何真人或机构的官方意见。<br><strong>免责声明：</strong>本工具仅用于高考志愿填报初步分析和思路参考，不构成最终填报建议。录取结果受当年招生计划、专业组设置、选科要求、位次变化、政策调整等多种因素影响。最终请以本省教育考试院、学校招生章程和正式志愿填报系统为准。</div></div>';
}
function isGaokaoChat(c){return c&&c.mode!=='fun';}
function newChat(){var id=Date.now()+'';chats[id]={name:'新对话',mode:'gaokao',msgs:[]};curId=id;save();render();}
function delChat(id){delete chats[id];if(curId===id){var ks=Object.keys(chats).filter(function(k){return isGaokaoChat(chats[k]);});curId=ks.length?ks[ks.length-1]:null;if(!curId)newChat();}save();render();}
function save(){try{localStorage.setItem('xf_chats',JSON.stringify(chats));localStorage.setItem('xf_cur',curId||'');}catch(e){console.warn('save failed:',e.message);}}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function render(){
  try{var h='';Object.keys(chats).forEach(function(id){var c=chats[id];if(!isGaokaoChat(c))return;var p=(c.msgs&&c.msgs.length)?(c.msgs[c.msgs.length-1].content||'').slice(0,18):'空';var on=id===curId?' on':'';h+='<div class=\"item'+on+'\" data-id=\"'+id+'\">'+(c.name||p)+'<span style=\"float:right;opacity:0.4;cursor:pointer\" data-del=\"'+id+'\">x</span></div>';});
  var cl=S('chatList');if(cl)cl.innerHTML=h;
  var m=S('msgArea');if(!m)return;
  if(!curId||!chats[curId]||!chats[curId].msgs||!chats[curId].msgs.length){m.innerHTML=welcomeHTML();return;}
  var hh='';var ms=chats[curId].msgs;for(var i=0;i<ms.length;i++){var x=ms[i];if(!x)continue;var who=x.role==='user'?'你':'志愿分析助手';var cls=x.role==='user'?'u':'a';hh+='<div class=\"bubble '+cls+'\"><div class=\"who\">'+who+'</div>'+esc(x.content||'')+'</div>';}
  m.innerHTML=hh;m.scrollTop=m.scrollHeight;}catch(e){console.warn('render error:',e.message);}
}

async function send(){
  var inp=S('inp');if(!inp)return;var t=inp.value.trim();if(!t)return;inp.value='';
  if(!curId||!isGaokaoChat(chats[curId]))newChat();var c=chats[curId];if(!c){c={name:'新对话',mode:'gaokao',msgs:[]};chats[curId]=c;}c.msgs.push({role:'user',content:t});if(c.name==='新对话')c.name=t.slice(0,16);render();save();
  var a=S('msgArea');if(!a)return;var ld=document.createElement('div');ld.className='bubble a';ld.innerHTML='<div class=\"who\">...</div><span class=\"dot\"></span><span class=\"dot\"></span><span class=\"dot\"></span>';a.appendChild(ld);a.scrollTop=a.scrollHeight;
  var cfg=getCfg();if(!cfg.key){c.msgs.push({role:'assistant',content:'请先点API设置填写Key'});render();save();return;}
  var dh=await queryData(t);
  var ms=[{role:'system',content:PG}];
  console.log('dataHint length:',dh.length);
  if(dh&&dh.indexOf('暂无数据')<0){ms.push({role:'system',content:'【以下是查询到的真实数据，你必须逐条引用，并据此给出冲稳保建议】\n'+dh});}
  else if(dh){ms.push({role:'system',content:'【查询结果】\n'+dh+'\n\n数据库未返回有效数据。你可以结合联网搜索结果给出方向性建议，但绝对禁止编造具体分数和位次数字。'});}
  else{ms.push({role:'system',content:'【注意】数据库和联网搜索均未找到具体数据。你必须明确说"暂无该省该专业的录取数据"，建议查省教育考试院官网。不准编造任何具体位次和分数数字。可以给择校方向建议，但要注明"以下为方向性建议，非具体数据"。'});}
  var info=extractInfo(t);if(info.province){var pr='【省份志愿政策提醒】';var ng={'浙江':80,'山东':96,'河北':96,'重庆':96,'辽宁':112};var gg={'江苏':40,'广东':45,'湖北':45,'湖南':45,'福建':40,'北京':30,'天津':50,'上海':24,'海南':24,'河南':48,'四川':45,'陕西':45,'山西':45,'云南':40,'贵州':45,'内蒙古':45,'安徽':45,'江西':45,'黑龙江':40,'吉林':40,'广西':40,'甘肃':45,'新疆':45,'宁夏':45,'青海':45,'西藏':45};if(ng[info.province]){pr+=info.province+'是专业+院校模式，可填'+ng[info.province]+'个志愿。你必须推荐足够多的学校(至少30-50所)，不要只给3-5所！';}else if(gg[info.province]){pr+=info.province+'是院校+专业组模式，可填'+gg[info.province]+'个专业组。你必须推荐足够数量，填满80%以上位置！';}else{pr+=info.province+'请推荐足够多的学校和专业，并提醒注意调剂风险。';}ms.push({role:'system',content:pr});}
  for(var i=Math.max(0,c.msgs.length-25);i<c.msgs.length;i++)ms.push({role:c.msgs[i].role,content:c.msgs[i].content});
  try{
    var r=await fetch(cfg.url.replace(/\/+$/,'')+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+cfg.key},body:JSON.stringify({model:cfg.model||'deepseek-chat',messages:ms,temperature:0.7})});
    if(!r.ok){var e=await r.json().catch(function(){return{};});throw new Error(e.error&&e.error.message||'HTTP '+r.status);}
    var d=await r.json();var reply=d.choices[0].message.content;
    if(dh&&dh.indexOf('暂无数据')<0)reply='[查询到的数据]\n'+dh+'\n---\n'+reply;
    else reply='[查询参数] '+dh+'\n---\n'+reply;
    c.msgs.push({role:'assistant',content:reply});
  }catch(e){c.msgs.push({role:'assistant',content:'出错：'+e.message});}
  render();save();
}

// ===== 智能数据提取（正则，无需API） =====
function extractInfo(t){
  var info={province:'',rank:0,score:0,major:'',school:''};
  // 省份：找文本中最先出现的那个（不是列表中最先的）
  var provs=['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','广西','海南','四川','贵州','云南','西藏','陕西','甘肃','青海','宁夏','新疆','内蒙古'];
  var bestIdx=t.length,bestProv='';
  for(var i=0;i<provs.length;i++){
    var idx=t.indexOf(provs[i]);
    if(idx>=0&&idx<bestIdx){bestIdx=idx;bestProv=provs[i];}
  }
  info.province=bestProv;
  var rm=t.match(/(\d{4,7})\s*[位名]/)||t.match(/[位名]次?\s*(\d{4,7})/)||t.match(/排[名行]\s*(\d{4,7})/);
  if(rm){info.rank=parseInt(rm[1])||parseInt(rm[2])||0;}
  var sm=t.match(/(\d{3})\s*分/);if(sm){info.score=parseInt(sm[1]);}
  // 专业：过滤掉否定句式中的词（不学X/不接受X/不读X/不选X/别推荐X）
  var majors=['计算机','软件','电气','机械','自动化','土木','临床','口腔','法学','会计','金融','物联网','人工智能','大数据','电子','通信','材料','化工','生物','医学','护理','师范','英语','日语','新闻','设计','美术','音乐','体育','汉语言','思政','马克思','数学','化学','地理','航空航天','能源','交通','环境'];
  var neg=t.match(/(?:不学|不接受|不读|不选|别推荐|别学|拒绝|排斥|不想学|不考虑).*?(?:[。，,;\n]|$)/g)||[];
  // 也排除描述性用语：XX一般/不好/不行/差/弱/烂，XX好/擅长这类不是专业偏好
  var desc=t.match(/(?:英语|数学|语文|物理|化学|生物|历史|地理|政治).*?(?:一般|不好|不行|差|弱|烂|还行|凑合|勉强)/g)||[];
  var desc2=t.match(/(?:英语|数学|语文|物理|化学|生物|历史|地理|政治).*?(?:好|不错|擅长|强|可以|能行)/g)||[];
  var negStr=neg.join('')+desc.join('')+desc2.join('');
  var found=[];
  for(var i=0;i<majors.length;i++){
    if(t.indexOf(majors[i])>=0&&negStr.indexOf(majors[i])<0){found.push(majors[i]);}
  }
  if(found.length>0)info.major=found.join(',');
  var sch=t.match(/[一-鿿]{2,8}(大学|学院)/);if(sch){info.school=sch[0];}
  return info;
}

// ===== 联网搜索：Tavily优先，Baidu兜底 =====
async function searchWeb(query, cfg, n){
  n=n||3;var results=[];
  if(cfg.tavily){
    try{
      var ctrl=new AbortController();var to=setTimeout(function(){ctrl.abort();},12000);
      var r=await fetch('https://api.tavily.com/search',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+cfg.tavily},body:JSON.stringify({query:query,search_depth:'basic',include_answer:true,max_results:n}),signal:ctrl.signal});
      clearTimeout(to);
      if(r.ok){var d=await r.json();if(d.answer)results.push('[Tavily总结] '+d.answer);if(d.results){d.results.forEach(function(x){results.push(x.title+': '+x.content.slice(0,300));});}}
    }catch(e){console.warn('Tavily failed:',e.message);}
  }
  if(!results.length){
    try{
      var r2=await fetch('/search?q='+encodeURIComponent(query));
      if(r2.ok){var d2=await r2.json();if(d2.results){d2.results.forEach(function(x){results.push(x);});}}
    }catch(e){console.warn('Baidu search failed:',e.message);}
  }
  return results;
}

// ===== 主数据管线：AI分析提取→DB搜→联网搜→整合 =====
async function queryData(t){
  var cfg=getCfg();
  var info={province:'',rank:0,score:0,majors:[],schools:[],keywords:[]};

  // 直接正则提取（不用AI，避免API卡住）
  var re=extractInfo(t);
  info.province=re.province||'';
  info.rank=re.rank||0;
  info.score=re.score||0;
  info.majors=re.major?[re.major]:[];
  info.schools=re.school?[re.school]:[];
  console.log('正则提取:',JSON.stringify(info));

  console.log('DEBUG queryData params:',JSON.stringify({province:info.province,rank:info.rank,score:info.score,majors:info.majors}));
  if(!info.province&&!info.score){console.log('缺少省份和分数，跳过DB');return'缺少省份或分数位次';}

  // 第3步：搜索本地数据库
  var dbData='';
  try{
    var qp=['province='+encodeURIComponent(info.province),'rank='+info.rank,'score='+info.score];
    if(info.majors&&info.majors.length){qp.push('keyword='+encodeURIComponent(info.majors.join(',')));}
    if(info.schools.length)qp.push('school='+encodeURIComponent(info.schools[0]));
    var resp=await fetch('recommend?'+qp.join('&'));
    if(resp.ok){
      var j=await resp.json();
      if(j.chong||j.wen||j.bao){
        dbData='【本地数据库·冲稳保推荐】位次'+j.rank+'\n';
        if(j.chong&&j.chong.length){dbData+='\n▎冲 (录取位次高于你，可以试试):\n';j.chong.slice(0,7).forEach(function(d){dbData+='· '+d.school+' '+d.major+' '+d.year+'年 最低'+(d.score||'?')+'分 位次'+(d.rank||'?')+'\n';});}
        if(j.wen&&j.wen.length){dbData+='\n▎稳 (位次匹配，有把握):\n';j.wen.slice(0,7).forEach(function(d){dbData+='· '+d.school+' '+d.major+' '+d.year+'年 最低'+(d.score||'?')+'分 位次'+(d.rank||'?')+'\n';});}
        if(j.bao&&j.bao.length){dbData+='\n▎保 (历史位次留有较大安全边际):\n';j.bao.slice(0,7).forEach(function(d){dbData+='· '+d.school+' '+d.major+' '+d.year+'年 最低'+(d.score||'?')+'分 位次'+(d.rank||'?')+'\n';});}
        if(!j.chong.length&&!j.wen.length&&!j.bao.length){dbData+='(数据库暂无数据。查询参数: 省='+info.province+' 位次='+info.rank+' 分数='+info.score+' 关键词='+(info.majors.join(',')||'无')+')\n';}
      }
    }
  }catch(e){console.warn('DB搜索失败:',e.message);}

  // 第4步：联网搜索——三路并发：验证DB数据 + 补全2025 + 行业趋势
  var webData='';
  try{
    var queries=[];
    // 路1：验证DB学校（冲稳保各5所，搜最新分数线）
    var dbSchools=[];
    if(j&&j.chong)for(var i=0;i<Math.min(5,j.chong.length);i++)dbSchools.push(j.chong[i].school);
    if(j&&j.wen)for(var i=0;i<Math.min(5,j.wen.length);i++)dbSchools.push(j.wen[i].school);
    if(j&&j.bao)for(var i=0;i<Math.min(5,j.bao.length);i++)dbSchools.push(j.bao[i].school);
    for(var i=0;i<dbSchools.length;i++){
      queries.push(dbSchools[i]+' '+info.province+' 2025录取分数线位次 王牌专业');
    }
    // 路2：补全DB没有的2025数据
    if(info.majors.length&&info.province){
      queries.push(info.province+' 2025年 '+info.majors[0]+'专业 录取位次 本科批');
      queries.push(info.province+' '+info.rank+'位次 2025 能报哪些大学 '+info.majors.join(' '));
    }
    // 路3：行业趋势和就业
    if(info.majors.length){
      queries.push(info.majors[0]+'专业 2025 2026 就业前景 薪资 行业趋势');
    }
    // AI提取的关键词也加上
    if(info.keywords&&info.keywords.length){
      for(var i=0;i<Math.min(2,info.keywords.length);i++)queries.push(info.keywords[i]);
    }
    // 去重query
    var seenQ={};var finalQ=[];
    for(var i=0;i<queries.length;i++){if(!seenQ[queries[i]]){seenQ[queries[i]]=1;finalQ.push(queries[i]);}}
    // 分3批并行搜索（每批5个同时发，避免限流）
    var allWeb=[];
    for(var b=0;b<finalQ.length;b+=3){
      var batch=finalQ.slice(b,b+5);
      var tasks=[];for(var i=0;i<batch.length;i++){tasks.push(searchWeb(batch[i],cfg,2));}
      try{var results=await Promise.all(tasks);for(var i=0;i<results.length;i++){allWeb=allWeb.concat(results[i]);}}catch(e){console.warn('批次搜索失败:',e.message);}
    }
    var seen={};var unique=[];
    for(var i=0;i<allWeb.length;i++){var k=allWeb[i].slice(0,50);if(!seen[k]){seen[k]=1;unique.push(allWeb[i]);}}
    if(unique.length){webData='【联网搜索·仅供参考】\n';unique.slice(0,15).forEach(function(w){webData+='· '+w.slice(0,300)+'\n';});}
  }catch(e){console.warn('联网搜索失败:',e.message);}

  // 第5步：整合
  var result='[DEBUG] province='+info.province+' rank='+info.rank+' score='+info.score+' majors='+(info.majors||[]).join(',')+'\n';
  if(dbData)result+=dbData+'\n';
  if(webData)result+=webData+'\n';
  if(!dbData&&!webData)result+='DB和联网搜索均无结果。查询URL: recommend?province='+encodeURIComponent(info.province)+'&rank='+info.rank+'&score='+info.score+'&keyword='+encodeURIComponent((info.majors||[]).join(','))+'\n';
  return result;
}
function getCfg(){return{url:localStorage.getItem('cf_url')||'https://api.deepseek.com',key:localStorage.getItem('cf_key')||'',model:localStorage.getItem('cf_model')||'deepseek-chat',tavily:localStorage.getItem('cf_tav')||''};}
function openSet(){var ov=S('setOverlay');if(ov)ov.style.display='flex';var c=getCfg();var su=S('sUrl'),sk=S('sKey'),sm=S('sModel'),st=S('sTav');if(su)su.value=c.url;if(sk)sk.value=c.key;if(sm)sm.value=c.model;if(st)st.value=c.tavily;}
function closeApiHelp(){var h=S('apiKeyHelp'),b=S('apiKeyHelpBtn');if(h)h.classList.remove('open');if(b)b.setAttribute('aria-expanded','false');}
function closeSet(){var ov=S('setOverlay');if(ov)ov.style.display='none';closeApiHelp();}
async function testConn(){var su=S('sUrl'),sk=S('sKey'),sm=S('sModel'),sv=S('sTav'),stt=S('st');if(!su||!sk||!stt)return;var u=su.value.trim(),k=sk.value.trim(),m=sm?sm.value.trim():'',tv=sv?sv.value.trim():'';if(!u||!k){stt.innerHTML='<span class=\"st b\">请填写URL和Key</span>';return;}try{localStorage.setItem('cf_url',u);localStorage.setItem('cf_key',k);localStorage.setItem('cf_model',m);if(tv)localStorage.setItem('cf_tav',tv);}catch(e){}stt.textContent='测试中...';try{var r=await fetch(u.replace(/\/+$/,'')+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+k},body:JSON.stringify({model:m||'deepseek-chat',messages:[{role:'user',content:'hi'}],max_tokens:5})});if(r.ok){stt.innerHTML='<span class=\"st g\">连接OK</span>';setTimeout(closeSet,800);}else{var e=await r.json().catch(function(){return{};});stt.innerHTML='<span class=\"st b\">'+(e.error&&e.error.message||'')+'</span>';}}catch(e){stt.innerHTML='<span class=\"st b\">'+e.message+'</span>';}}

// Event bindings
function B(id,ev,fn){var el=S(id);if(el)el[ev]=fn;}
B('newBtn','onclick',function(){newChat();});B('sendBtn','onclick',function(){send();});
B('themeBtn','onclick',function(){document.body.classList.toggle('dark');localStorage.setItem('xf_dark',document.body.classList.contains('dark')?'1':'');});
B('apiBtn','onclick',function(){openSet();});B('closeSetBtn','onclick',function(){closeSet();});B('testBtn','onclick',function(){testConn();});
B('apiKeyHelpBtn','onclick',function(e){e.stopPropagation();var h=S('apiKeyHelp');var open=h&&h.classList.toggle('open');this.setAttribute('aria-expanded',open?'true':'false');});
B('setOverlay','onclick',function(e){if(e.target===this)closeSet();});
document.addEventListener('click',function(e){var h=S('apiKeyHelp');if(h&&!h.contains(e.target))closeApiHelp();});
B('inp','onkeydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
B('msgArea','onclick',function(e){var btn=e.target.closest('.example-btn');if(!btn)return;var inp=S('inp');if(inp){inp.value=btn.dataset.example||'';inp.focus();}});
B('chatList','onclick',function(e){var el=e.target;if(el.dataset.del){delChat(el.dataset.del);return;}var item=el.closest('.item');if(item){curId=item.dataset.id;render();save();}});
// init
try{
if(localStorage.getItem('xf_dark')==='1')document.body.classList.add('dark');
if(!curId||!isGaokaoChat(chats[curId])){var ks=Object.keys(chats).filter(function(id){return isGaokaoChat(chats[id]);});if(ks.length){curId=ks[ks.length-1];}else{var nid=Date.now()+'';chats[nid]={name:'新对话',mode:'gaokao',msgs:[]};curId=nid;}save();}
try{localStorage.removeItem('xf_mode');}catch(e){}
render();
}catch(e){console.warn('init error:',e.message);document.body.innerHTML='<div style=\"padding:40px;text-align:center\"><h2>加载失败</h2><p>请清除浏览器缓存后刷新 (Ctrl+Shift+Del)</p></div>';}
</script></body></html>'''

def main():
    port = 8766
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'雪峰志愿分析助手: http://127.0.0.1:{port}/')
    print(f'数据库: {"已加载" if HAS_DB else "未找到"}')
    try: server.serve_forever()
    except KeyboardInterrupt: server.shutdown(); print('\n已停止')

if __name__ == '__main__': main()
