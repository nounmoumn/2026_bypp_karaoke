"""Build a local listening and timestamp review page for Bansanka A."""

import csv
import json
from pathlib import Path


root = Path("data/poc/bansanka")
asr = json.loads((root / "alignment_whisperx_sequential.json").read_text(encoding="utf-8"))["lines"]
score = json.loads((root / "alignment_whisperx_sequential_musicxml.json").read_text(encoding="utf-8"))["lines"]
rough = list(csv.DictReader((root / "segment_A_reference_manual_rough.csv").open(encoding="utf-8-sig", newline="")))
assert len(asr) == len(score) == len(rough) == 18

rows = []
for a, s, r in zip(asr, score, rough):
    assert a["lineId"] == s["lineId"] == r["line_id"]
    rows.append({
        "id": a["lineId"], "jp": a["jp"], "ko": r["reading_ko"],
        "asrStart": a["startSec"], "asrEnd": a["endSec"],
        "scoreStart": s["startSec"], "scoreEnd": s["endSec"],
        "roughStart": float(r["reference_start"]), "roughEnd": float(r["reference_end"]),
    })

payload = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
html = r'''<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>晩餐歌 정렬 경계 검수</title>
<style>
body{font:16px/1.5 system-ui,sans-serif;background:#111;color:#eee;max-width:980px;margin:24px auto;padding:0 16px}
h1{font-size:1.5rem} .note{color:#bbb}.panel{position:sticky;top:0;background:#1b1b1b;padding:14px;border:1px solid #444;z-index:2}
audio{width:100%}button,input{font:inherit}button{background:#333;color:#fff;border:1px solid #777;border-radius:6px;padding:6px 10px;cursor:pointer}
button:hover,button:focus{background:#555}button.primary{background:#235eab}.actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
table{width:100%;border-collapse:collapse;margin:20px 0}th,td{padding:8px;border-bottom:1px solid #333;text-align:left;vertical-align:top}
tr.active{background:#26364d}tr.flag{border-left:4px solid #f0aa36} .lyric{font-size:1.08rem}small{color:#bbb}
input[type=number]{width:78px;background:#222;color:#fff;border:1px solid #777;padding:4px}
.times{font-variant-numeric:tabular-nums;white-space:nowrap}.row-actions{display:flex;gap:5px;flex-wrap:wrap}
@media(max-width:650px){table,thead,tbody,tr,td{display:block}thead{display:none}tr{padding:10px;margin:10px 0;border:1px solid #444}td{border:0;padding:3px}.panel{position:static}}
</style>
<h1>晩餐歌 구간 A — 줄 경계 검수</h1>
<p class="note">시각은 원곡 8.0초를 뺀 59초 구간 기준입니다. 「현재 줄 듣기」는 적힌 시작부터 끝까지만 딱 재생합니다. 노란 표시는 두 자동 후보의 시작이나 끝이 0.5초 넘게 다른 줄입니다. 아래 값은 제안일 뿐이며, 귀로 듣고 확정한 후 CSV로 내보내세요.</p>
<div class="panel"><label>듣는 오디오 <select id="source"><option value="segment_A_0008.0-0067.0.wav">원곡 구간</option><option value="demucs_output/htdemucs/segment_A_0008.0-0067.0/vocals.wav">분리 보컬</option><option value="demucs_output/htdemucs/segment_A_0008.0-0067.0/no_vocals.wav">반주 MR 원키</option><option value="pitch_output/mr_shift_-5.wav">반주 MR -5</option><option value="pitch_output/mr_shift_+5.wav">반주 MR +5</option></select></label><audio id="audio" controls preload="metadata" src="segment_A_0008.0-0067.0.wav"></audio>
<div class="actions"><button id="prev">← 이전 줄</button><button id="play" class="primary">현재 줄 듣기</button><button id="next">다음 줄 →</button><button id="markStart">현재 시각 → 시작</button><button id="markEnd">현재 시각 → 끝</button><button id="confirm">현재 줄 확인 완료</button><button id="export">확정 CSV 내보내기</button></div>
<div id="status" aria-live="polite"></div><small>단축키: ←/→ 줄 이동, Space 재생/정지, S 시작 찍기, E 끝 찍기. 숫자 입력 중에는 작동하지 않습니다.</small></div>
<table><thead><tr><th>줄</th><th>자동 후보 / 기존 거친 기록</th><th>검수 값 (초)</th><th>듣기</th></tr></thead><tbody id="rows"></tbody></table>
<script>
const DATA = __DATA__;
const audio = document.getElementById('audio'), tbody = document.getElementById('rows'), status = document.getElementById('status');
document.getElementById('source').addEventListener('change',e=>{const t=audio.currentTime,playing=!audio.paused;audio.src=e.target.value;audio.addEventListener('loadedmetadata',()=>{audio.currentTime=Math.min(t,audio.duration);if(playing)audio.play().catch(()=>{});},{once:true});});
const key = 'bansanka_A_review_v1'; let selected = 0, stopAt = null;
let marks = DATA.map(r => ({start:r.scoreStart,end:r.scoreEnd,checked:false}));
try { const saved=JSON.parse(localStorage.getItem(key)); if(Array.isArray(saved)&&saved.length===DATA.length) marks=saved; } catch {}
function save(){localStorage.setItem(key,JSON.stringify(marks));}
function fmt(v){return Number(v).toFixed(3)}
function select(i){selected=Math.max(0,Math.min(DATA.length-1,i)); render(); document.getElementById(DATA[selected].id).scrollIntoView({block:'nearest'});}
function playLine(i){select(i); const m=marks[i]; const start=Number(m.start), end=Number(m.end); if(!Number.isFinite(start)||!Number.isFinite(end)||start>=end){status.textContent='시작·끝을 확인하세요.';return;}
  audio.currentTime=Math.max(0,start);stopAt=Math.min(59,end);audio.play().catch(e=>status.textContent='재생 실패: '+e.message);}
function watch(){if(stopAt!==null&&audio.currentTime>=stopAt){audio.pause();audio.currentTime=stopAt;stopAt=null;}}
audio.addEventListener('timeupdate',watch);setInterval(watch,10);
function mark(which){const v=Number(audio.currentTime.toFixed(3)); marks[selected][which]=v; marks[selected].checked=true;save();render();}
function set(i,which,v){marks[i][which]=Number(v);marks[i].checked=true;save();render();}
function render(){tbody.replaceChildren();DATA.forEach((r,i)=>{const m=marks[i];const diff=Math.max(Math.abs(r.scoreStart-r.asrStart),Math.abs(r.scoreEnd-r.asrEnd));
 const tr=document.createElement('tr');tr.id=r.id;tr.className=(i===selected?'active ':'')+(diff>0.5?'flag':'');
 const lyric=document.createElement('td');lyric.innerHTML='<b>'+r.id+'</b> <span class="lyric"></span><br><small></small>';lyric.querySelector('.lyric').textContent=r.jp;lyric.querySelector('small').textContent=r.ko;
 const compare=document.createElement('td');compare.className='times';compare.textContent=`ASR창 ${fmt(r.asrStart)}–${fmt(r.asrEnd)}\n채보창 ${fmt(r.scoreStart)}–${fmt(r.scoreEnd)}\n거친 탭 ${fmt(r.roughStart)}–${fmt(r.roughEnd)}`;compare.style.whiteSpace='pre-line';
 const edit=document.createElement('td');for(const field of ['start','end']){const label=document.createElement('label');label.textContent=field==='start'?'시작 ':'끝 ';const input=document.createElement('input');input.type='number';input.min=0;input.max=59;input.step=.001;input.value=fmt(m[field]);input.addEventListener('change',()=>set(i,field,input.value));label.append(input);edit.append(label,document.createElement('br'));}const check=document.createElement('small');check.textContent=m.checked?'✓ 청취 검수 표시':'○ 미검수';edit.append(check);
 const controls=document.createElement('td');controls.className='row-actions';for(const [text,fn] of [['듣기',()=>playLine(i)],['확인 완료',()=>{marks[i].checked=true;save();render();}],['ASR창',()=>{marks[i]={start:r.asrStart,end:r.asrEnd,checked:false};save();render();}],['채보창',()=>{marks[i]={start:r.scoreStart,end:r.scoreEnd,checked:false};save();render();}],['거친 탭',()=>{marks[i]={start:r.roughStart,end:r.roughEnd,checked:false};save();render();}]]){const b=document.createElement('button');b.textContent=text;b.onclick=fn;controls.append(b)}
 tr.append(lyric,compare,edit,controls);tbody.append(tr);}); const r=DATA[selected],m=marks[selected];status.textContent=`선택: ${r.id} / ${DATA.filter((_,i)=>marks[i].checked).length}줄 청취 검수 표시 / 현재 ${fmt(m.start)}–${fmt(m.end)}초`;}
document.getElementById('prev').onclick=()=>select(selected-1);document.getElementById('next').onclick=()=>select(selected+1);
document.getElementById('play').onclick=()=>playLine(selected);document.getElementById('markStart').onclick=()=>mark('start');document.getElementById('markEnd').onclick=()=>mark('end');document.getElementById('confirm').onclick=()=>{marks[selected].checked=true;save();render();};
document.getElementById('export').onclick=()=>{const cols=['sample_id','line_id','lyrics','reference_start','reference_end','timing_source','review_note'];const quote=v=>'"'+String(v).replaceAll('"','""')+'"';
 const lines=[cols.join(',')];DATA.forEach((r,i)=>{const m=marks[i];lines.push(['bansanka_A',r.id,r.jp,fmt(m.start),fmt(m.end),m.checked?'manual_reviewed':'candidate_unreviewed',m.checked?'listened in review page':'not listened'].map(quote).join(','));});
 const blob=new Blob(['\ufeff'+lines.join('\r\n')+'\r\n'],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='segment_A_reference_reviewed.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
document.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;if(e.key==='ArrowLeft'){e.preventDefault();select(selected-1)}else if(e.key==='ArrowRight'){e.preventDefault();select(selected+1)}else if(e.key===' '){e.preventDefault();audio.paused?audio.play():audio.pause()}else if(e.key.toLowerCase()==='s')mark('start');else if(e.key.toLowerCase()==='e')mark('end');});
render();
</script></html>'''
(root / "review_alignment.html").write_text(html.replace("__DATA__", payload), encoding="utf-8")
print(root / "review_alignment.html")
