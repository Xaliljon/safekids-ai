"""The annotation editor page — one embedded HTML string, zero CDNs.

Shortcuts: ←/→ frame step, shift+←/→ jump 10, space play/pause,
1-4 label select, drag on the canvas = new box, click a box + X = delete,
E = start/finish an event span at the playhead, U/Z = undo, Y = redo,
S = save. Autosave runs on every edit anyway (the session guarantees it).
"""

PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Guardian Annotator</title>
<style>
 body{background:#101218;color:#dee2e8;font:14px Menlo,monospace;margin:0;padding:16px}
 h1{font-size:16px;color:#6eaaff;margin:0 0 10px}
 #wrap{display:flex;gap:16px}
 canvas{background:#000;border:1px solid #3c424e;cursor:crosshair}
 #side{width:330px}
 button{background:#1c2028;color:#dee2e8;border:1px solid #3c424e;border-radius:4px;
        padding:4px 10px;margin:2px;font:13px Menlo,monospace;cursor:pointer}
 button:hover{border-color:#6eaaff}
 select{background:#1c2028;color:#dee2e8;border:1px solid #3c424e;padding:3px}
 #timeline{height:46px;background:#181c24;border:1px solid #3c424e;margin-top:8px;
           position:relative;cursor:pointer}
 .ev{position:absolute;top:22px;height:16px;background:#e6c85a;opacity:.85;
     border-radius:3px;font-size:10px;color:#101218;overflow:hidden;padding-left:3px}
 .ev.fall{background:#f06e6e}
 #cursor{position:absolute;top:0;width:2px;height:100%;background:#6eaaff}
 #status{color:#8a919d;margin-top:8px;min-height:18px}
 .box-row{padding:2px 4px;border-radius:3px}
 .box-row.sel{background:#243044}
 kbd{background:#242a34;border-radius:3px;padding:0 4px;color:#a8d0ff}
 #help{color:#8a919d;font-size:12px;line-height:1.7;margin-top:10px}
</style></head><body>
<h1>GUARDIAN ANNOTATOR <span id="clip"></span></h1>
<div id="wrap">
 <div>
  <canvas id="cv" width="640" height="480"></canvas>
  <div id="timeline"><div id="cursor"></div></div>
  <div>
   <button onclick="step(-10)">&#171;</button><button onclick="step(-1)">&#8249;</button>
   <button id="play" onclick="togglePlay()">play</button>
   <button onclick="step(1)">&#8250;</button><button onclick="step(10)">&#187;</button>
   <span id="pos"></span>
  </div>
 </div>
 <div id="side">
  <div>label <select id="label">
    <option>person</option><option>child</option><option>adult</option><option>unknown</option>
  </select>
  event <select id="evlabel">
    <option>fall</option><option>walking</option><option>standing</option>
    <option>sitting</option><option>lying</option><option>unknown</option>
  </select></div>
  <div>
   <button onclick="cmd('undo')">undo (U)</button><button onclick="cmd('redo')">redo (Y)</button>
   <button onclick="cmd('save')">save (S)</button>
   <button onclick="eventKey()">event (E)</button>
   <button onclick="delSelected()">delete box (X)</button>
  </div>
  <div id="boxes"></div>
  <div id="events"></div>
  <div id="status">autosave on — every edit is persisted</div>
  <div id="help">drag = draw box &#183; click box = select &#183;
   <kbd>&#8592;</kbd><kbd>&#8594;</kbd> step &#183; <kbd>space</kbd> play &#183;
   <kbd>E</kbd> event span at playhead &#183; <kbd>X</kbd> delete &#183;
   <kbd>U</kbd>/<kbd>Y</kbd> undo/redo &#183; <kbd>S</kbd> save</div>
 </div>
</div>
<script>
let A=null,frame=0,playing=null,sel=-1,drag=null,evStart=null;
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
const img=new Image();img.onload=draw;
async function state(){const r=await fetch('/api/state');A=await r.json();
 document.getElementById('clip').textContent=A.annotation.clip_id;render();}
function fr(){return (A.annotation.frames||[]).find(f=>f.index===frame);}
function load(){img.src='/frame/'+frame+'.jpg?'+Date.now();
 document.getElementById('pos').textContent=frame+' / '+(A.annotation.frame_count-1);
 document.getElementById('cursor').style.left=
   (frame/(A.annotation.frame_count-1)*100)+'%';render();}
function draw(){ctx.drawImage(img,0,0,cv.width,cv.height);const f=fr();
 if(f)f.boxes.forEach((b,i)=>{ctx.strokeStyle=i===sel?'#6eaaff':'#50dc82';
  ctx.lineWidth=2;ctx.strokeRect(b.box[0]*cv.width,b.box[1]*cv.height,
   b.box[2]*cv.width,b.box[3]*cv.height);
  ctx.fillStyle=i===sel?'#6eaaff':'#50dc82';
  ctx.fillText(b.label,b.box[0]*cv.width+3,b.box[1]*cv.height+12);});
 if(drag){ctx.strokeStyle='#e6c85a';
  ctx.strokeRect(drag.x,drag.y,drag.w,drag.h);}}
function render(){load();const f=fr(),bx=document.getElementById('boxes');
 bx.innerHTML='<b>boxes @ frame</b>';
 (f?f.boxes:[]).forEach((b,i)=>{const d=document.createElement('div');
  d.className='box-row'+(i===sel?' sel':'');d.textContent=i+': '+b.label;
  d.onclick=()=>{sel=i;render();};bx.appendChild(d);});
 const tl=document.getElementById('timeline');
 tl.querySelectorAll('.ev').forEach(e=>e.remove());
 const ev=document.getElementById('events');ev.innerHTML='<b>events</b>';
 (A.annotation.events||[]).forEach((e,i)=>{const d=document.createElement('div');
  d.className='box-row';
  d.textContent=e.label+' ['+e.start_frame+'..'+e.end_frame+']  ✕';
  d.onclick=()=>apply({op:'delete_event',event_index:i});ev.appendChild(d);
  const s=document.createElement('div');s.className='ev '+e.label;
  const n=A.annotation.frame_count-1;
  s.style.left=(e.start_frame/n*100)+'%';
  s.style.width=Math.max(1,(e.end_frame-e.start_frame)/n*100)+'%';
  s.textContent=e.label;tl.appendChild(s);});
 status(A.can_undo?'history: '+(A.can_undo?'undo ready':''):'');}
function status(t){document.getElementById('status').textContent=t||'autosave on';}
async function apply(p){const r=await fetch('/api/apply',{method:'POST',
 body:JSON.stringify(p)});const j=await r.json();
 if(j.error){status('rejected: '+j.error);}else{A=j;sel=-1;render();}}
async function cmd(c,p){const r=await fetch('/api/'+c,{method:'POST',
 body:JSON.stringify(p||{})});const j=await r.json();
 if(j.error){status('rejected: '+j.error);}else{A=j;render();status(c+' ok');}}
function step(d){frame=Math.min(Math.max(frame+d,0),A.annotation.frame_count-1);
 sel=-1;load();}
function togglePlay(){const b=document.getElementById('play');
 if(playing){clearInterval(playing);playing=null;b.textContent='play';return;}
 b.textContent='pause';
 playing=setInterval(()=>{if(frame>=A.annotation.frame_count-1)togglePlay();
  else step(1);},1000/A.annotation.fps);}
function eventKey(){if(evStart===null){evStart=frame;
  status('event start @ '+frame+' — press E again at the end');}
 else{apply({op:'add_event',label:document.getElementById('evlabel').value,
  start:Math.min(evStart,frame),end:Math.max(evStart,frame)});evStart=null;}}
function delSelected(){const f=fr();if(f&&sel>=0)
 apply({op:'delete_box',frame:frame,box_index:sel});}
cv.onmousedown=e=>{const r=cv.getBoundingClientRect();
 drag={x:e.clientX-r.left,y:e.clientY-r.top,w:0,h:0};};
cv.onmousemove=e=>{if(!drag)return;const r=cv.getBoundingClientRect();
 drag.w=e.clientX-r.left-drag.x;drag.h=e.clientY-r.top-drag.y;draw();};
cv.onmouseup=e=>{if(!drag)return;const d=drag;drag=null;
 if(Math.abs(d.w)<4||Math.abs(d.h)<4){selectAt(d.x,d.y);return;}
 const x=Math.min(d.x,d.x+d.w)/cv.width,y=Math.min(d.y,d.y+d.h)/cv.height;
 apply({op:'add_box',frame:frame,label:document.getElementById('label').value,
  box:[Math.max(0,x),Math.max(0,y),Math.abs(d.w)/cv.width,Math.abs(d.h)/cv.height]});};
function selectAt(x,y){const f=fr();if(!f)return;sel=-1;
 f.boxes.forEach((b,i)=>{const bx=b.box[0]*cv.width,by=b.box[1]*cv.height,
  bw=b.box[2]*cv.width,bh=b.box[3]*cv.height;
  if(x>=bx&&x<=bx+bw&&y>=by&&y<=by+bh)sel=i;});render();}
document.getElementById('timeline').onclick=e=>{
 const r=e.currentTarget.getBoundingClientRect();
 frame=Math.round((e.clientX-r.left)/r.width*(A.annotation.frame_count-1));load();};
document.onkeydown=e=>{
 if(e.target.tagName==='SELECT')return;
 const k=e.key.toLowerCase();
 if(e.key==='ArrowRight')step(e.shiftKey?10:1);
 else if(e.key==='ArrowLeft')step(e.shiftKey?-10:-1);
 else if(k===' '){e.preventDefault();togglePlay();}
 else if(k==='u'||k==='z')cmd('undo');
 else if(k==='y')cmd('redo');
 else if(k==='s'){e.preventDefault();cmd('save');}
 else if(k==='e')eventKey();
 else if(k==='x')delSelected();
 else if(k>='1'&&k<='4')document.getElementById('label').selectedIndex=k-1;};
state();
</script></body></html>
"""
