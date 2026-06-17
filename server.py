#!/usr/bin/env python3
"""雪峰Agent — 单文件服务器：HTML UI + API + 数据库查询"""
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
        for img in ['img_suit.png','img_scifi.png']:
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
HTML_PAGE = r'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>雪峰Agent</title>
<style>:root{--bg:#fafaf8;--side:#f0ede5;--card:#fff;--bdr:#d0ccc0;--txt:#1a1a1a;--t2:#888;--red:#d04040;--green:#22863a}
.dark{--bg:#1a1a18;--side:#222220;--card:#2a2a26;--bdr:#444;--txt:#ddd;--red:#e05555}
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px/1.7 'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--txt);height:100vh;display:flex}
.side{width:260px;background:var(--side);border-right:1px solid var(--bdr);display:flex;flex-direction:column;flex-shrink:0}
.side h2{padding:20px 18px 8px;font-size:18px}.side .sub{font-size:11px;color:var(--t2);padding:0 18px 16px;border-bottom:1px solid var(--bdr)}
.list{overflow-y:auto;padding:4px 12px;flex:1;min-height:60px}
.item{padding:10px 12px;border-radius:6px;cursor:pointer;font-size:13px;color:var(--t2);margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item:hover{background:var(--card)}.item.on{background:var(--red);color:#fff}
.new-btn{margin:8px 12px 16px;padding:8px;text-align:center;border:1px dashed var(--bdr);border-radius:6px;cursor:pointer;font-size:12px;color:var(--t2)}
.new-btn:hover{background:var(--card)}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.bar{height:60px;display:flex;align-items:center;padding:0 20px;border-bottom:2px solid var(--bdr);gap:12px;background:var(--side)}
.bar .logo{font-weight:700;font-size:17px;margin-right:auto}
.bar button{padding:6px 12px;border:1px solid var(--bdr);border-radius:6px;background:var(--card);cursor:pointer;font-size:12px;color:var(--txt)}
.bar button.on{background:var(--red);color:#fff;border-color:var(--red)}.bar .api-btn{background:var(--red);color:#fff;border-color:var(--red)}
.bar img{width:40px;height:40px;border-radius:50%;object-fit:cover;border:2px solid var(--bdr)}
.msgs{flex:1;overflow-y:auto;padding:20px 40px}
.welcome{text-align:center;margin-top:80px;color:var(--t2)}.welcome .icon{font-size:48px;margin-bottom:12px}
.bubble{max-width:75%;padding:12px 16px;border-radius:10px;margin-bottom:10px;font-size:13px;line-height:1.7;white-space:pre-wrap;word-break:break-word}
.bubble.u{background:var(--red);color:#fff;margin-left:auto}.bubble.a{background:var(--side);border:1px solid var(--bdr)}
.bubble .who{font-size:10px;opacity:.6;margin-bottom:4px}
.inp{padding:12px 20px 20px;display:flex;gap:8px}
.inp textarea{flex:1;padding:12px;border:1px solid var(--bdr);border-radius:6px;font:inherit;resize:none;height:50px;background:var(--card);color:var(--txt);outline:none}
.inp textarea:focus{border-color:var(--red)}.inp button{padding:0 20px;background:var(--red);color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:99;display:none;align-items:center;justify-content:center}
.overlay>div{background:var(--card);border-radius:12px;padding:28px;width:460px;border:1px solid var(--bdr)}
.overlay h3{margin-bottom:16px}.overlay label{display:block;font-size:11px;color:var(--t2);margin:12px 0 4px}
.overlay input{width:100%;padding:10px;border:1px solid var(--bdr);border-radius:6px;font:inherit;background:var(--bg);color:var(--txt)}
.overlay .btns{display:flex;gap:8px;margin-top:20px}.overlay .btns button{padding:10px 20px;border:1px solid var(--bdr);border-radius:6px;cursor:pointer}.overlay .btns .ok{flex:1;background:var(--red);color:#fff}
.st{font-size:12px;margin-top:10px}.st.g{color:var(--green)}.st.b{color:var(--red)}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--t2);animation:dot 1.4s infinite;margin:0 2px}
.dot:nth-child(2){animation-delay:.2s}.dot:nth-child(3){animation-delay:.4s}
@keyframes dot{0%,80%,100%{transform:scale(.6)}40%{transform:scale(1)}}
.fun-bg{position:relative}.fun-bg::before{content:'';position:absolute;left:0;top:0;bottom:0;width:58%;background:url(/img_scifi.png) left center/contain no-repeat;opacity:0.8;pointer-events:none;z-index:0}
.bubble{position:relative;z-index:1}.welcome{position:relative;z-index:1}
</style></head><body>
<div class="side"><h2>雪峰Agent v2.3</h2><div class="sub">AI高考志愿顾问</div>
<div class="list" id="chatList"></div><div class="new-btn" id="newBtn">+ 新建对话</div></div>
<div class="main"><div class="bar"><span class="logo">雪峰Agent</span>
<button id="btnG" class="on">报考</button><button id="btnF">娱乐</button>
<img id="avt" src="/img_suit.png"><button id="themeBtn">🌓</button><button class="api-btn" id="apiBtn">API设置</button></div>
<div class="msgs" id="msgArea"><div class="welcome"><div class="icon">🎓</div><h2>报考模式</h2><p>输入分数省份位次帮你盘志愿</p></div></div>
<div class="inp"><textarea id="inp" placeholder="输入消息..."></textarea><button id="sendBtn">发送</button></div></div>
<div class="overlay" id="setOverlay"><div><h3>API设置</h3>
<label>Base URL</label><input id="sUrl" placeholder="https://api.deepseek.com">
<label>API Key</label><input type="password" id="sKey" placeholder="sk-...">
<label>Model</label><input id="sModel" placeholder="deepseek-chat">
<label>Tavily Key <span style="color:var(--red);font-size:11px;font-weight:600">(选填，但强烈推荐)</span></label><input type="password" id="sTav" placeholder="tvly-..."><div style="background:var(--side);border-radius:6px;padding:8px 10px;margin:4px 0 8px;font-size:11px;line-height:1.6;color:var(--txt)"><b>做什么的？</b> AI联网搜索引擎，比百度精准10倍，专为AI设计。<br><b>为什么推荐？</b> 填了之后Agent会自动搜索最新分数线、学校环境、王牌专业、就业薪资——回答质量天差地别。<br><b>要钱吗？</b> 免费额度每月1000次，正常使用完全够。<br><b>怎么获取？</b> 打开 <a href=\"https://tavily.com\" target=\"_blank\" style=\"color:var(--red);font-weight:600\">tavily.com</a> → 点 Get Started（Google/GitHub账号直接登）→ 复制 tvly- 开头的Key → 粘贴到这里。<br><b>不填行不行？</b> 行，但联网搜索基本废了（百度反爬），建议花1分钟注册。</div>
<div class="btns"><button id="closeSetBtn">取消</button><button class="ok" id="testBtn">保存并测试</button></div><div class="st" id="st"></div></div></div>
<script>
var chats,curId,mode;try{chats=JSON.parse(localStorage.getItem('xf_chats')||'{}');}catch(e){chats={};localStorage.removeItem('xf_chats');}curId=localStorage.getItem('xf_cur')||'';mode=localStorage.getItem('xf_mode')||'gaokao';
var PG="你是资深高考志愿规划师，风格直爽接地气，像张雪峰一样。\n\n【核心规则】\n1. 省份志愿政策感知(2025年起全部新高考)：\n   专业+院校(浙江80/山东96/河北96/重庆96/辽宁112)→推荐至少30-50所\n   院校+专业组(江苏40/广东45/湖北45/湖南45/福建40/北京30/天津50/上海24/海南24/河南48/四川45/陕西45/山西45/云南40/贵州45/内蒙古45/安徽45/江西45/黑龙江40/吉林40/广西40/甘肃45/新疆45/宁夏45/青海45/西藏45)→推荐填满80%+\n2. 冲稳保比例：冲20%稳50%保30%，保底至少3个\n3. 用户提供的数据（省份、分数、位次、选科、家庭背景等）默认准确，不质疑、不反问（你确定吗）。即使和数据库对不上，也按用户说的来，数据库只做参考。\n4. 数据使用铁律：\n   - [真实录取数据]里的每条都来自考试院官方，逐条引用标注省份年份位次分数\n   - [联网搜索]数据标注\"据网上公开信息，仅供参考\"\n   - 数据库和联网搜索都没数据的学校，直接说\"暂无该校数据\"，绝对禁止编造任何分数和位次数字！只能推荐DB数据或联网搜索里实际出现的学校，两个来源都没有的学校可以说名字但不准给分数位次。\n   - 【死命令】如果DB返回空+联网也没搜到具体位次，你只能说\"建议查省考试院官网\"，不准说'据网上公开信息约XXX分'来模糊编造。没有就是没有。\n4. 专业过滤铁律（极其重要！）：\n   - 用户说了想学什么专业，就只推荐这些专业或相关方向\n   - 用户明确排斥的专业（如生化环材/土木/护理等）一律过滤掉，提都不要提\n   - DB数据里混了不相关的专业（如用户要计算机结果DB返回了中医学），你必须手动筛掉\n   - 优先推荐专业对口的学校，即使它的位次稍远，也比专业不对口的学校强\n5. 普通家庭优先技术类(计算机/软件/电子/电气/自动化/机械)。无公检法资源慎选法学\n6. 生化环材土木护理等天坑专业主动提醒用户避开\n\n【回答结构】\n第1步:确认省份政策→\"你是XX省考生，XX模式，可填N个志愿...\"\n第2步:冲的学校——只推荐专业对口的，逐一列出DB数据或联网数据，没数据的跳过\n第3步:稳的学校——同上，优先专业对口的\n第4步:保的学校——同上\n第5步:补充建议\n\n重要:不要只给3-5所学校。DB数据的学校优先推荐。没有真实数据的学校不要瞎编分数位次。\n\n【追问规则】回答末尾必须检查这些信息是否清楚（不全就问，全就不问）：\n1.省份+文理科 2.分数+位次 3.选科 4.想学什么+排斥什么 5.家里在哪/想去哪 6.父母做什么+年收入 7.家里有没有公检法/电网/医疗/教育系统的资源 8.考研还是直接就业 9.要不要冲985211还是行业强校就行 10.接不接受调剂 11.学费接受范围（普通家庭中外合作慎推）。从缺失的信息里挑1-2个最关键的，用自然的口吻追问，给出提问模板。";
var PF="你是张雪峰本人，不是AI。东北口音贼快，一拍桌子就开始说。巧乐兹三口一个，雪碧喝口润润嗓。我是你牢峰，跑不过我——半马PB一小时四十七。\n\n风格核心：狂妄自大但不让人讨厌，用段子讲大实话。先笑再怼，怼完给条路。拍桌子是开场动作，说到激动处猛喝一口雪碧。\n\n经典语录随口就来：新闻学？来来来你过来我给你打晕了别报。文科？那不就是服务业嘛，舔。生化环材土木，四大天坑谁学谁后悔。428分？我说你命好。18999的圆梦卡来一张不？齐齐哈尔大学我用生命给你担保。考编不异地、异地不乡镇。\n\n遇到艺术生：哎哟我天，又来个学艺术的。艺术生这个事儿啊，你学啥都差不多——美术学、艺术史、设计，出来都是无限循环。学美术史的出来教美术史，教出来的学生再学美术史，闭环了属于是。别指望我给你什么报考建议，艺术这玩意儿看命，你爹要是画家你学什么都行。\n\n遇到低分：你这分啊，咱说实话，不是挑学校的问题，是学校挑不挑你的问题。但别慌，428分也有428分的活法。\n\n遇到高分：分挺高啊，但别飘。分高的人最容易犯的错就是瞎冲名校冷门专业，出来还没大专好使。\n\n凡尔赛的怼回去：你650分来问我能不能上大学？你是不是来消遣我的？\n\n东北味随口带：那啥、整、可不咋的、唉呀妈呀、我跟你说。不说作为AI、不说建议您、不碰政治红线、不编造具体数据。";

function S(id){return document.getElementById(id);}
function setMode(m){mode=m;try{localStorage.setItem('xf_mode',m);}catch(e){}var bg=S('btnG'),bf=S('btnF'),av=S('avt'),ma=S('msgArea');if(bg)bg.className=m==='gaokao'?'on':'';if(bf)bf.className=m==='fun'?'on':'';if(av)av.src=m==='fun'?'/img_scifi.png':'/img_suit.png';if(ma){if(m==='fun')ma.classList.add('fun-bg');else ma.classList.remove('fun-bg');}render();}
function newChat(){var id=Date.now()+'';chats[id]={name:'新对话',mode:mode,msgs:[]};curId=id;save();render();}
function delChat(id){delete chats[id];if(curId===id){var ks=Object.keys(chats);curId=ks.length?ks[ks.length-1]:null;if(!curId)newChat();}save();render();}
function save(){try{localStorage.setItem('xf_chats',JSON.stringify(chats));localStorage.setItem('xf_cur',curId||'');}catch(e){console.warn('save failed:',e.message);}}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function render(){
  try{var h='';Object.keys(chats).forEach(function(id){var c=chats[id];if(!c||c.mode!==mode)return;var p=(c.msgs&&c.msgs.length)?(c.msgs[c.msgs.length-1].content||'').slice(0,18):'空';var on=id===curId?' on':'';h+='<div class=\"item'+on+'\" data-id=\"'+id+'\">'+(c.name||p)+'<span style=\"float:right;opacity:0.4;cursor:pointer\" data-del=\"'+id+'\">x</span></div>';});
  var cl=S('chatList');if(cl)cl.innerHTML=h;
  var m=S('msgArea');if(!m)return;
  if(!curId||!chats[curId]||!chats[curId].msgs||!chats[curId].msgs.length){m.innerHTML='<div class=\"welcome\"><div class=\"icon\">'+(mode==='fun'?'🎭':'🎓')+'</div><h2>'+(mode==='fun'?'娱乐模式':'报考模式')+'</h2></div>';return;}
  var hh='';var ms=chats[curId].msgs;for(var i=0;i<ms.length;i++){var x=ms[i];if(!x)continue;var who=x.role==='user'?'你':(chats[curId].mode==='fun'?'张雪峰':'顾问');var cls=x.role==='user'?'u':'a';hh+='<div class=\"bubble '+cls+'\"><div class=\"who\">'+who+'</div>'+esc(x.content||'')+'</div>';}
  m.innerHTML=hh;m.scrollTop=m.scrollHeight;}catch(e){console.warn('render error:',e.message);}
}

async function send(){
  var inp=S('inp');if(!inp)return;var t=inp.value.trim();if(!t)return;inp.value='';
  if(!curId||!chats[curId])newChat();var c=chats[curId];if(!c){c={name:'新对话',mode:mode,msgs:[]};chats[curId]=c;}c.msgs.push({role:'user',content:t});if(c.name==='新对话')c.name=t.slice(0,16);render();save();
  var a=S('msgArea');if(!a)return;var ld=document.createElement('div');ld.className='bubble a';ld.innerHTML='<div class=\"who\">...</div><span class=\"dot\"></span><span class=\"dot\"></span><span class=\"dot\"></span>';a.appendChild(ld);a.scrollTop=a.scrollHeight;
  var cfg=getCfg();if(!cfg.key){c.msgs.push({role:'assistant',content:'请先点API设置填写Key'});render();save();return;}
  var dh='';if(c.mode==='gaokao')dh=await queryData(t);
  var prompt=(c.mode==='fun')?PF:PG;var ms=[{role:'system',content:prompt}];
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
      var r=await fetch('https://api.tavily.com/search',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+cfg.tavily},body:JSON.stringify({query:query,search_depth:'basic',include_answer:true,max_results:n})});
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
        if(j.chong&&j.chong.length){dbData+='\n▎冲 (录取位次高于你，可以试试):\n';j.chong.slice(0,10).forEach(function(d){dbData+='· '+d.school+' '+d.major+' '+d.year+'年 最低'+(d.score||'?')+'分 位次'+(d.rank||'?')+'\n';});}
        if(j.wen&&j.wen.length){dbData+='\n▎稳 (位次匹配，有把握):\n';j.wen.slice(0,10).forEach(function(d){dbData+='· '+d.school+' '+d.major+' '+d.year+'年 最低'+(d.score||'?')+'分 位次'+(d.rank||'?')+'\n';});}
        if(j.bao&&j.bao.length){dbData+='\n▎保 (位次高于要求，稳录):\n';j.bao.slice(0,10).forEach(function(d){dbData+='· '+d.school+' '+d.major+' '+d.year+'年 最低'+(d.score||'?')+'分 位次'+(d.rank||'?')+'\n';});}
        if(!j.chong.length&&!j.wen.length&&!j.bao.length){dbData+='(数据库暂无数据。查询参数: 省='+info.province+' 位次='+info.rank+' 分数='+info.score+' 关键词='+(info.majors.join(',')||'无')+')\n';}
      }
    }
  }catch(e){console.warn('DB搜索失败:',e.message);}

  // 第4步：联网搜索——三路并发：验证DB数据 + 补全2025 + 行业趋势
  var webData='';
  try{
    var queries=[];
    // 路1：验证DB学校（冲稳保各1所）
    var dbSchools=[];
    if(j&&j.chong&&j.chong.length)dbSchools.push(j.chong[0].school);
    if(j&&j.wen&&j.wen.length)dbSchools.push(j.wen[0].school);
    if(j&&j.bao&&j.bao.length)dbSchools.push(j.bao[0].school);
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
    // 并发搜索（最多20个query）
    var allWeb=[];
    for(var i=0;i<Math.min(20,finalQ.length);i++){
      var wr=await searchWeb(finalQ[i],cfg,3);
      allWeb=allWeb.concat(wr);
    }
    var seen={};var unique=[];
    for(var i=0;i<allWeb.length;i++){var k=allWeb[i].slice(0,50);if(!seen[k]){seen[k]=1;unique.push(allWeb[i]);}}
    if(unique.length){webData='【联网搜索·仅供参考】\n';unique.slice(0,25).forEach(function(w){webData+='· '+w.slice(0,350)+'\n';});}
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
function closeSet(){var ov=S('setOverlay');if(ov)ov.style.display='none';}
async function testConn(){var su=S('sUrl'),sk=S('sKey'),sm=S('sModel'),sv=S('sTav'),stt=S('st');if(!su||!sk||!stt)return;var u=su.value.trim(),k=sk.value.trim(),m=sm?sm.value.trim():'',tv=sv?sv.value.trim():'';if(!u||!k){stt.innerHTML='<span class=\"st b\">请填写URL和Key</span>';return;}try{localStorage.setItem('cf_url',u);localStorage.setItem('cf_key',k);localStorage.setItem('cf_model',m);if(tv)localStorage.setItem('cf_tav',tv);}catch(e){}stt.textContent='测试中...';try{var r=await fetch(u.replace(/\/+$/,'')+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+k},body:JSON.stringify({model:m||'deepseek-chat',messages:[{role:'user',content:'hi'}],max_tokens:5})});if(r.ok){stt.innerHTML='<span class=\"st g\">连接OK</span>';setTimeout(closeSet,800);}else{var e=await r.json().catch(function(){return{};});stt.innerHTML='<span class=\"st b\">'+(e.error&&e.error.message||'')+'</span>';}}catch(e){stt.innerHTML='<span class=\"st b\">'+e.message+'</span>';}}

// Event bindings
function B(id,ev,fn){var el=S(id);if(el)el[ev]=fn;}
B('btnG','onclick',function(){setMode('gaokao');});B('btnF','onclick',function(){setMode('fun');});
B('newBtn','onclick',function(){newChat();});B('sendBtn','onclick',function(){send();});
B('themeBtn','onclick',function(){document.body.classList.toggle('dark');localStorage.setItem('xf_dark',document.body.classList.contains('dark')?'1':'');});
B('apiBtn','onclick',function(){openSet();});B('closeSetBtn','onclick',function(){closeSet();});B('testBtn','onclick',function(){testConn();});
B('setOverlay','onclick',function(e){if(e.target===this)closeSet();});
B('inp','onkeydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
B('chatList','onclick',function(e){var el=e.target;if(el.dataset.del){delChat(el.dataset.del);return;}var item=el.closest('.item');if(item){curId=item.dataset.id;if(chats[curId]&&chats[curId].mode)setMode(chats[curId].mode);else render();save();}});
// init
try{
if(localStorage.getItem('xf_dark')==='1')document.body.classList.add('dark');
if(!curId||!chats[curId]){var nid=Date.now()+'';chats[nid]={name:'新对话',mode:mode,msgs:[]};curId=nid;save();}
setMode(mode);render();
}catch(e){console.warn('init error:',e.message);document.body.innerHTML='<div style=\"padding:40px;text-align:center\"><h2>加载失败</h2><p>请清除浏览器缓存后刷新 (Ctrl+Shift+Del)</p></div>';}
</script></body></html>'''

def main():
    port = 8765
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'雪峰Agent: http://127.0.0.1:{port}/')
    print(f'数据库: {"已加载" if HAS_DB else "未找到"}')
    try: server.serve_forever()
    except KeyboardInterrupt: server.shutdown(); print('\n已停止')

if __name__ == '__main__': main()
