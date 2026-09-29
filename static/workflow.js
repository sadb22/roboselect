const csrf=()=>document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=')[1]||document.querySelector('[name=csrfmiddlewaretoken]')?.value;
async function auth(action,data){const r=await fetch('/api/auth/'+action+'/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw Error(result.error);location.href=action==='logout'?'/':result.admin&&new URLSearchParams(location.search).get('role')==='admin'?'/workspace/robots/':'/studies/';}
document.querySelector('#auth')?.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);try{await auth(e.submitter.value,{username:f.get('username'),password:f.get('password'),role:new URLSearchParams(location.search).get('role')});}catch(err){document.querySelector('#auth-error').textContent=err.message;}});
document.querySelector('#logout')?.addEventListener('click',()=>auth('logout',{}));
const initial=document.querySelector('#initial-requirements');
if(initial){
 const req=JSON.parse(initial.textContent),types=JSON.parse(document.querySelector('#operation-types').textContent);
 const fields=[['area','Площадь склада, м²',10,1e6],['active_area','Рабочая зона, м²',10,1e6],['aisle_m','Минимальный проход, м',.3,20],['payload_kg','Масса паллеты, кг',1,50000],['temperature','Температура, °C',-60,70],['peak_hour','Пиковый поток, паллет/ч',1,1000],['daily_moves','Паллет в сутки',1,24000],['clearance_m','Боковой зазор, м',.05,1]];
 function input(parent,label,key,value,options={}){const l=document.createElement('label');l.textContent=label;const el=document.createElement('input');el.name=key;el.value=value??'';el.type=options.type||'text';el.required=true;if(el.type==='number'){el.step='any';el.min=options.min;el.max=options.max;}l.append(el);parent.append(l);return el;}
 function select(parent,label,key,choices,value,multiple=false){const l=document.createElement('label');l.textContent=label;const el=document.createElement('select');el.name=key;el.multiple=multiple;for(const [v,t] of choices){const o=document.createElement('option');o.value=v;o.textContent=t;o.selected=multiple?value.includes(v):v===value;el.append(o);}l.append(el);parent.append(l);return el;}
 for(const [key,label,min,max] of fields)input(document.querySelector('#warehouse-fields'),label,key,req[key],{type:'number',min,max});
 document.querySelector('#allow-human').checked=req.allow_human;
 function capture(){
  req.routes=[...document.querySelectorAll('.route-editor')].map(row=>Object.fromEntries([...row.querySelectorAll('input')].map(el=>[el.name,el.type==='number'?Number(el.value):el.value])));
  req.operations=[...document.querySelectorAll('.op-editor')].map(row=>Object.fromEntries([...row.querySelectorAll('input,select')].map(el=>[el.name,el.multiple?[...el.selectedOptions].map(o=>o.value):el.type==='number'?Number(el.value):el.value])));
 }
 function draw(){
  const routes=document.querySelector('#routes-editor');routes.replaceChildren();
  req.routes.forEach((r,i)=>{const row=document.createElement('div');row.className='route-editor card fields';routes.append(row);input(row,'ID проезда','id',r.id);input(row,'Название','name',r.name);for(const [k,t] of [['width_m','Ширина, м'],['x1','Начало X'],['y1','Начало Y'],['x2','Конец X'],['y2','Конец Y']])input(row,t,k,r[k],{type:'number',min:0,max:k==='width_m'?20:100});const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent='Удалить проезд';b.onclick=()=>{capture();req.routes.splice(i,1);draw();};row.append(b);});
  const ops=document.querySelector('#operations-editor');ops.replaceChildren();
  req.operations.forEach((o,i)=>{const row=document.createElement('section');row.className='op-editor card operation';ops.append(row);const grid=document.createElement('div');grid.className='fields';row.append(grid);input(grid,'ID операции','id',o.id);input(grid,'Название','name',o.name);select(grid,'Тип операции','code',Object.entries(types),o.code);select(grid,'Предыдущие операции (Ctrl / ⌘ для нескольких)','predecessors',req.operations.filter(x=>x.id!==o.id).map(x=>[x.id,x.name]),o.predecessors,true);select(grid,'Проезд','route',[['','Нет'],...req.routes.map(r=>[r.id,r.name])],o.route);for(const [k,t,max] of [['distance_m','Маршрут в одну сторону, м',1000],['lift_m','Высота подъёма, м',30],['buffer','Входной буфер, паллет (0: ожидание у исполнителя)',100],['stations','Параллельных мест выполнения',30]])input(grid,t,k,o[k],{type:'number',min:k==='stations'?1:0,max});const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent='Удалить операцию';b.onclick=()=>{capture();req.operations.splice(i,1);req.operations.forEach(x=>x.predecessors=x.predecessors.filter(p=>p!==o.id));draw();};row.append(b);});
 }
 draw();document.querySelector('#add-route').onclick=()=>{capture();if(req.routes.length>=6)return alert('Не более 6 проездов');req.routes.push({id:'route'+Date.now(),name:'Новый проезд',width_m:3,x1:10,y1:30,x2:90,y2:30});draw();};
 document.querySelector('#add-operation').onclick=()=>{capture();if(req.operations.length>=6)return alert('Не более 6 операций');req.operations.push({id:'op'+Date.now(),name:'Новая операция',code:'warehouse_pallet_transport',predecessors:[],route:'',distance_m:0,lift_m:0,buffer:4,stations:2});draw();};
 document.querySelector('#study-form').addEventListener('submit',()=>{capture();for(const [key] of fields)req[key]=Number(document.querySelector('#warehouse-fields [name='+key+']').value);req.allow_human=document.querySelector('#allow-human').checked;document.querySelector('#requirements').value=JSON.stringify(req);});
}
document.querySelectorAll('form:not(#auth)').forEach(form=>form.addEventListener('submit',()=>{setTimeout(()=>{form.querySelectorAll('button[type=submit],button:not([type])').forEach(b=>{b.disabled=true;b.textContent='Обработка…';});},0);}));
const canvas=document.querySelector('#workflow-playback');
if(canvas){
 const sim=JSON.parse(document.querySelector('#simulation-data').textContent),req=JSON.parse(document.querySelector('#simulation-requirements').textContent),groups=JSON.parse(document.querySelector('#simulation-groups').textContent);
 const ctx=canvas.getContext('2d'),events=sim.events||[],end=Math.max(1,...events.map(e=>e.end));let time=0,playing=false,last=0;
 const colors=['#147d72','#3276bd','#a25996','#b98014','#6a70a5','#ab5338'];
 const positions=Object.fromEntries(req.operations.map((o,i)=>[o.id,{x:90+i*900/Math.max(1,req.operations.length-1),y:180+(i%2)*60}]));
 function draw(){ctx.fillStyle='#f2f6f5';ctx.fillRect(0,0,1100,520);ctx.font='14px sans-serif';
  for(const r of req.routes){ctx.strokeStyle='#ccdcd8';ctx.lineWidth=Math.max(8,r.width_m*9);ctx.beginPath();ctx.moveTo(r.x1*10+40,r.y1*2+65);ctx.lineTo(r.x2*10+40,r.y2*2+65);ctx.stroke();ctx.fillStyle='#536660';ctx.fillText(r.name+' · '+r.width_m+' м',r.x1*10+40,r.y1*2+45);}
  for(const o of req.operations){const p=positions[o.id];for(const prev of o.predecessors){ctx.strokeStyle='#829c98';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(positions[prev].x,positions[prev].y);ctx.lineTo(p.x,p.y);ctx.stroke();}
   ctx.fillStyle='#fff';ctx.fillRect(p.x-70,p.y-40,140,80);ctx.strokeStyle='#aac6c0';ctx.strokeRect(p.x-70,p.y-40,140,80);ctx.fillStyle='#253a35';ctx.fillText(o.name.slice(0,22),p.x-65,p.y-15);ctx.fillText('Буфер: '+o.buffer,p.x-65,p.y+8);ctx.fillText('Мест: '+o.stations,p.x-65,p.y+28);}
  const active=new Map();for(const e of events)if(e.start<=time&&e.end>time)active.set(e.group+':'+(e.worker||0),e);
  groups.forEach((g,gi)=>{const color=colors[gi%colors.length];ctx.fillStyle=color;ctx.fillText(g.id+': '+(g.data?.model||'Люди').slice(0,28),25+(gi%3)*350,365+Math.floor(gi/3)*80);ctx.fillStyle='#d9e8c5';ctx.fillRect(25+(gi%3)*350,380+Math.floor(gi/3)*80,130,26);ctx.fillStyle='#354730';ctx.fillText('Зарядка: '+(g.chargers||0),30+(gi%3)*350,398+Math.floor(gi/3)*80);
   for(let w=0;w<g.count;w++){const e=active.get(g.id+':'+w);let x=25+(gi%3)*350+w*15,y=335+Math.floor(gi/3)*80;
    if(e){if(e.phase==='charge'){x=40+(gi%3)*350+w*15;y=392+Math.floor(gi/3)*80;}else{const o=req.operations.find(o=>o.id===e.operation),p=positions[e.operation],r=req.routes.find(r=>r.id===o.route),f=(time-e.start)/(e.end-e.start);x=p.x;y=p.y+45+w*13;if(r){x=(r.x1+(r.x2-r.x1)*(f<.5?f*2:(1-f)*2))*10+40;y=(r.y1+(r.y2-r.y1)*(f<.5?f*2:(1-f)*2))*2+65+w*10;}}}
    ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.fill();}}
  );document.querySelector('#sim-clock').textContent='Время прогона: '+Math.floor(time/60)+' мин '+Math.floor(time%60)+' с · активных событий: '+active.size+' · длительность: '+Math.ceil(end/60)+' мин';
 }
 function frame(now){if(playing){time=Math.min(end,time+(now-last)/1000*Number(document.querySelector('#sim-speed').value));if(time>=end)playing=false;draw();}last=now;requestAnimationFrame(frame);}
 document.querySelector('#sim-play').onclick=()=>{if(time>=end)time=0;playing=true;};document.querySelector('#sim-pause').onclick=()=>playing=false;document.querySelector('#sim-reset').onclick=()=>{playing=false;time=0;draw();};
 document.querySelector('#sim-image').onclick=()=>canvas.toBlob(blob=>{const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='roboscope-simulation.png';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);});draw();requestAnimationFrame(frame);
}
