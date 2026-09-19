"""Build a standalone, read-only V1/V2 Korean timing review page."""

import argparse
import json
from pathlib import Path


HTML = r'''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__ · 한국어 V2 검수</title>
<style>
:root{--bg:#090b18;--panel:#151a2d;--line:#303a59;--text:#f4f6ff;--muted:#9ca9c8;--cyan:#74f4ed;--pink:#ff759f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,"Malgun Gothic",sans-serif}
main{width:min(920px,100%);margin:auto;padding:22px}h1{font-size:1.35rem;margin:0 0 5px}.note{color:var(--muted);margin:0 0 16px}
.sticky{position:sticky;top:0;z-index:2;background:#090b18ee;padding:10px 0 14px;backdrop-filter:blur(10px)}audio{width:100%}
.now{min-height:76px;margin-top:10px;padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--panel);font-size:1.35rem;text-align:center}
.char{color:#606b88}.char.on{color:var(--cyan);text-shadow:0 0 10px #74f4ed55}.plain{color:var(--muted)}
.summary{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.tag{padding:5px 9px;border-radius:99px;background:#202642;color:var(--muted)}
.rows{display:grid;gap:7px}.row{display:grid;grid-template-columns:42px 1fr auto;gap:10px;align-items:center;width:100%;text-align:left;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;cursor:pointer}
.row:hover,.row.current{border-color:var(--cyan)}.n{color:var(--cyan);font-weight:800}.title{min-width:0}.timing{color:var(--muted);font:12px ui-monospace,monospace;white-space:nowrap}.delta{color:var(--pink)}
@media(max-width:600px){main{padding:14px}.row{grid-template-columns:32px 1fr}.timing{grid-column:2}}
</style><main><div class="sticky"><h1>__TITLE__ · 한국어 V2 검수</h1><p class="note">기존 공개 데이터는 변경하지 않았습니다. 줄을 누르면 V2 시작 시각으로 이동합니다.</p>
<audio id="audio" controls preload="metadata" src="__AUDIO__"></audio><div id="now" class="now">재생하면 현재 가사가 표시됩니다.</div></div>
<div class="summary"><span class="tag">V1 마지막 <b id="oldEnd"></b></span><span class="tag">V2 마지막 <b id="newEnd"></b></span><span class="tag">ASR 구간 <b id="groups"></b></span></div><div id="rows" class="rows"></div></main>
<script>const OLD=__OLD__,NEW=__NEW__;const au=document.getElementById('audio'),rows=document.getElementById('rows'),now=document.getElementById('now');
const sec=x=>`${Math.floor(x/60)}:${String(Math.floor(x%60)).padStart(2,'0')}.${Math.floor(x%1*10)}`;
oldEnd.textContent=sec(OLD.at(-1).end);newEnd.textContent=sec(NEW.lines.at(-1).end);groups.textContent=NEW.groups.length;
NEW.lines.forEach((l,i)=>{const o=OLD[i],b=document.createElement('button');b.className='row';b.innerHTML=`<span class="n">${String(i+1).padStart(2,'0')}</span><span class="title">${l.text}</span><span class="timing">V1 ${sec(o.start)} → V2 ${sec(l.start)} <span class="delta">${l.start-o.start>=0?'+':''}${(l.start-o.start).toFixed(1)}s</span></span>`;b.onclick=()=>{au.currentTime=Math.max(0,l.start-.5);au.play()};rows.append(b)});
function active(t){let hit=-1;for(let i=0;i<NEW.lines.length;i++){if(NEW.lines[i].start<=t)hit=i;else break}return hit}
function render(){const t=au.currentTime,i=active(t);[...rows.children].forEach((e,k)=>e.classList.toggle('current',k===i));if(i<0){now.textContent='전주';requestAnimationFrame(render);return}const l=NEW.lines[i],timed=l.chars.slice();let p=0,html='';for(const c of l.text){if(/[가-힣A-Za-z0-9]/.test(c)&&p<timed.length){const x=timed[p++];html+=`<span class="char ${t>=x.s?'on':''}">${c}</span>`}else html+=`<span class="plain">${c}</span>`}now.innerHTML=html;requestAnimationFrame(render)}render();</script></html>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--song", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--root", type=Path, default=Path("data/experiments/korean_v2"))
    parser.add_argument("--public-base", default="https://f1qfx0rjdk5hox-8888.proxy.runpod.net")
    args = parser.parse_args()
    folder = args.root / args.song
    old = json.loads((folder / "alignment_raw.json").read_text(encoding="utf-8"))["lines"]
    new = json.loads((folder / "candidate_v2.json").read_text(encoding="utf-8"))
    audio = f"{args.public_base}/api/songs/{args.song}/audio/original.mp3"
    page = (HTML.replace("__TITLE__", args.title).replace("__AUDIO__", audio)
            .replace("__OLD__", json.dumps(old, ensure_ascii=False).replace("<", "\\u003c"))
            .replace("__NEW__", json.dumps(new, ensure_ascii=False).replace("<", "\\u003c")))
    (folder / "review_v2.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
