(()=>{
'use strict';
const $=id=>document.getElementById(id);
let pollBusy=false,actionBusy=false;
const canControl=document.body.dataset.canControl==='1';
const clone=o=>JSON.parse(JSON.stringify(o));
const csrf=document.body.dataset.csrf||'';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctlWord=(v,yes='ENABLED',no='DISABLED')=>v===undefined||v===null?'UNKNOWN':Number(v)===1?yes:no;
const telemetryWord=v=>v===undefined||v===null?'UNKNOWN':({0:'ENABLED',1:'DISABLED',2:'ON DEMAND'})[Number(v)]??`MODE ${v}`;
function parseVersion(value){const m=String(value||'').trim().match(/^v?(\d+)\.(\d+)\.(\d+)/i);return m?[Number(m[1]),Number(m[2]),Number(m[3])]:null;}
function newerVersion(remote,local){const a=parseVersion(remote),b=parseVersion(local);if(!a||!b)return false;for(let i=0;i<3;i++){if(a[i]!==b[i])return a[i]>b[i];}return false;}
async function checkForUpdate(){const star=$('brandingStar'),label=$('updateVersion');if(!star)return;const local=String(star.dataset.localVersion||'').trim(),url=String(star.dataset.versionUrl||'').trim();star.classList.remove('has-update');star.title=local?`ASL3 Node Manager ${local}`:'ASL3 Node Manager repository';star.setAttribute('aria-label','Open the ASL3 Node Manager repository');if(label){label.hidden=true;label.textContent='';}if(!local||!url)return;try{const r=await fetch(url,{method:'GET',cache:'no-store'});if(!r.ok)return;const remote=String(await r.text()).trim();if(newerVersion(remote,local)){star.classList.add('has-update');star.title=`ASL3 Node Manager ${local} → ${remote} update available`;star.setAttribute('aria-label',`Open the ASL3 Node Manager repository. Update available from version ${local} to ${remote}.`);if(label){label.textContent=`Update available: ${local} → ${remote}`;label.hidden=false;}}}catch(_){}}
function nodeModeName(link){const c=String(link.mode_code||'');return c==='T'?'Node Transceiver':c==='R'?'Node Local Monitor':'AllStar Node';}
function rowIdentity(link){
  const type=String(link.connection_type||'').toLowerCase();
  const callsign=String(link.callsign||'').trim();
  const display=String(link.display_node||link.node||'?').trim();
  const description=String(link.description||'').trim();
  const location=String(link.location||'').trim();

  const match=callsign.toUpperCase().match(/\b([A-Z]{1,3}[0-9][A-Z0-9]{1,4})\b/);
  const qrz=match
    ? `<a href="https://www.qrz.com/db/${encodeURIComponent(match[1])}" target="_blank" rel="noopener noreferrer" title="Look up ${esc(match[1])} on QRZ" style="display:inline-flex;align-items:center;justify-content:center;flex:none;margin-left:5px;padding:0px 3px;border:1px solid #38bdf8;border-radius:4px;color:#38bdf8;font-size:9px;line-height:1.1;font-weight:700;text-decoration:none;vertical-align:middle;white-space:nowrap">QRZ</a>`
    : '';

  if(type==='node'){
    const main=callsign?`${display} · ${callsign}`:display;
    const details=[description,location].filter(Boolean).join(' — ');
    return `<span style="display:inline-flex;align-items:center;white-space:nowrap"><b>${esc(main)}</b>${qrz}</span><small>${esc(details||nodeModeName(link))}</small>`;
  }

  if(type==='echolink'){
    const main=callsign||display;
    const identity=callsign.toUpperCase();
    const kind=identity.endsWith('-R')?'EchoLink Repeater'
      :identity.endsWith('-L')?'EchoLink Link'
      :/^[A-Z]{1,3}[0-9][A-Z0-9]{1,4}$/.test(identity)?'EchoLink User'
      :identity?'EchoLink Conference':'EchoLink';
    const sub=display&&display!=='EchoLink ID unavailable'
      ? `${kind} · ${display}`:'EchoLink identity pending';
    return `<span style="display:inline-flex;align-items:center;white-space:nowrap"><b>${esc(main)}</b>${qrz}</span><small>${esc(sub)}</small>`;
  }

  return `<span style="display:inline-flex;align-items:center;white-space:nowrap"><b>${esc(callsign||display)}</b>${qrz}</span><small>Web Transceiver</small>`;
}
function directionBadge(link){
  const direction=String(link.direction||'').toUpperCase();
  if(direction==='OUT')return '<span class="direction-badge direction-out" title="Outgoing connection">↑ OUT</span> ';
  if(direction==='IN')return '<span class="direction-badge direction-in" title="Incoming connection">↓ IN</span> ';
  return '';
}
function modeBadge(link){const type=String(link.connection_type||'').toLowerCase();if(type==='echolink')return '<span class="mode-badge mode-echolink">E/L</span>';if(type==='client')return '<span class="mode-badge mode-wt">WT</span>';return '<span class="mode-badge mode-node">ASL</span>';}
function actionButton(label,action,target,klass='',confirmText=''){
  if(!canControl)return '';
  const help={
    disconnect:'Disconnect this active connection from the node. This does not block future connections.',
    block:'Disconnect this AllStar node and block it from reconnecting until access is restored.',
    restore:'Remove the block for this node. This allows future connections but does not initiate one.'
  };
  const tooltip=help[action]||label;
  return `<button type="button" class="row-action ${esc(klass)}" title="${esc(tooltip)}" data-action="${esc(action)}" data-target="${esc(target)}" data-result-box="connectionActionResult"${confirmText?` data-confirm="${esc(confirmText)}"`:''}>${esc(label)}</button>`;
}
function connectionActions(link){if(!canControl)return '<span class="view-only">VIEW ONLY</span>';const type=String(link.connection_type||'').toLowerCase(),target=String(link.control_target||link.node||'').trim(),shown=String(link.callsign||link.display_node||target||'connection').trim();const parts=[actionButton('Disconnect','disconnect',target,'danger',`Disconnect ${shown} now?`)];if(type==='node'&&/^\d{4,7}$/.test(target)&&!/^3\d{6}$/.test(target))parts.push(actionButton('Disconnect & Block','block',target,'block',`Disconnect and block node ${target}?`));return `<span class="row-actions">${parts.join('')}</span>`;}
function renderLinks(links){const body=$('linksBody');body.innerHTML='';if(!Array.isArray(links)||!links.length){body.innerHTML='<div class="empty">No current connections.</div>';return;}const ordered=links.slice().sort((a,b)=>Number(Boolean(b.keyed))-Number(Boolean(a.keyed))||String(a.display_node||a.node||'').localeCompare(String(b.display_node||b.node||''),undefined,{numeric:true,sensitivity:'base'}));for(const link of ordered){const row=document.createElement('div');row.className=link.keyed?'link-row keyed':'link-row';const st=document.createElement('span');st.innerHTML=`<span class="dot ${link.keyed?'bad':'ok'}"></span><b class="${link.keyed?'keyed-text':''}">${link.keyed?'KEYED':'CONNECTED'}</b>`;const n=document.createElement('span');n.className='node-identity';n.innerHTML=rowIdentity(link);const d=document.createElement('span');d.className='direction-cell';d.innerHTML=directionBadge(link);const m=document.createElement('span');m.innerHTML=modeBadge(link);const a=document.createElement('span');a.className='actions-cell';a.innerHTML=connectionActions(link);row.append(st,d,n,m,a);body.appendChild(row);}}
function renderBlocked(items){const body=$('blockedBody');if(!body)return;body.innerHTML='';$('blockedCount').textContent=String(Array.isArray(items)?items.length:0);if(!Array.isArray(items)||!items.length){body.innerHTML='<div class="empty">No blocked nodes.</div>';return;}for(const item of items){const row=document.createElement('div');row.className='blocked-row';const node=document.createElement('span'),main=item.callsign?`${item.node} · ${item.callsign}`:item.node;node.innerHTML=`<b>${esc(main)}</b>`;const reason=document.createElement('span');reason.textContent=item.reason||'Blocked';const action=document.createElement('span');action.innerHTML=canControl?actionButton('Restore Access','restore',String(item.node||''),'success',`Restore access for node ${item.node}?`):'<span class="view-only">VIEW ONLY</span>';row.append(node,reason,action);body.appendChild(row);}}
function syncAppearanceFromStatus(next){if(!next||typeof next!=='object'||Array.isArray(next))return;let changed=false;try{changed=JSON.stringify(next)!==JSON.stringify(appearance);}catch(_){return;}if(!changed)return;appearance=clone(next);applyAppearanceLocal(appearance);const menu=$('colorMenu');if(!menu||!menu.open){pending=clone(appearance);drawColors();}}
function formatBytes(value){if(!Number.isFinite(value))return 'N/A';const units=['B','KB','MB','GB','TB'];let n=Math.max(0,value),i=0;while(n>=1024&&i<units.length-1){n/=1024;i++;}return `${n>=100?Math.round(n):n.toFixed(1)} ${units[i]}`;}
function formatUptime(value){if(!Number.isFinite(value))return 'N/A';let s=Math.max(0,Math.floor(value));const d=Math.floor(s/86400);s%=86400;const h=Math.floor(s/3600);const m=Math.floor((s%3600)/60);return d?`${d}d ${h}h ${m}m`:`${h}h ${m}m`;}
function setSystemMetrics(raw){const s=raw&&typeof raw==='object'?raw:{};const set=(id,value)=>{const el=$(id);if(el)el.textContent=value;};const fmtP=v=>Number.isFinite(v)?`${v.toFixed(1)}%`:'N/A';set('sysLanIp',s.lan_ip||'N/A');const t=s.utc_time?new Date(s.utc_time):null;set('sysDateTime',t&&!Number.isNaN(t.getTime())?t.toLocaleString(undefined,{month:'2-digit',day:'2-digit',year:'numeric',hour:'numeric',minute:'2-digit'}):'N/A');set('sysCpu',fmtP(s.cpu_percent));set('sysRam',s.memory&&Number.isFinite(s.memory.used)&&Number.isFinite(s.memory.total)?`${formatBytes(s.memory.used)} / ${formatBytes(s.memory.total)}`:'N/A');set('sysNetUp',Number.isFinite(s.network_up_bps)?`${formatBytes(s.network_up_bps)}/s`:'N/A');set('sysNetDown',Number.isFinite(s.network_down_bps)?`${formatBytes(s.network_down_bps)}/s`:'N/A');set('sysTemp',Number.isFinite(s.temperature_f)?`${s.temperature_f.toFixed(1)} °F`:'N/A');set('sysUptime',formatUptime(s.uptime_seconds));set('sysRootDisk',fmtP(s.root_disk_percent));set('sysApacheDisk',fmtP(s.apache_disk_percent));}
function apply(status){setSystemMetrics(status.system_metrics);syncAppearanceFromStatus(status.appearance);const ctl=status.controller||{};$('nodeValue').textContent=status.node||'—';$('asteriskState').textContent=status.asterisk_online?'ONLINE':'OFFLINE';$('appRptState').textContent=status.node_online?'ONLINE':'UNAVAILABLE';$('systemTop').textContent=ctlWord(ctl.sys_ena);$('rxTop').textContent=status.rx_keyed?'KEYED':'IDLE';$('txTop').textContent=status.tx_keyed?'KEYED':'IDLE';$('rxTop').className=status.rx_keyed?'warn':'';$('txTop').className=status.tx_keyed?'danger-text':'';$('linksTop').textContent=String(status.adjacent_link_count??0);$('directCount').textContent=String(status.adjacent_link_count??0);$('allLinksState').textContent=String(status.all_link_count??0);$('autopatchState').textContent=status.autopatch_up?'UP':'DOWN';$('systemState').textContent=ctlWord(ctl.sys_ena);$('linkingState').textContent=ctlWord(ctl.link_ena);$('timeoutState').textContent=ctlWord(ctl.tot_ena);$('telemetryState').textContent=telemetryWord(ctl.tel_mode);$('systemControlState').textContent=ctlWord(ctl.sys_ena);$('incomingControlState').textContent=Number(ctl.iconns)===0?'BLOCKED':(Number(ctl.iconns)===1?'ALLOWED':'—');$('linkControlState').textContent=ctlWord(ctl.link_ena);$('connectionsControlState').textContent=String(status.adjacent_link_count??0);const c=status.channels||{};$('driverState').textContent=c.driver||'None';$('rxChannel').textContent=c.rxchannel||'—';$('txChannel').textContent=c.txchannel||'—';renderLinks(status.adjacent_links||[]);renderBlocked(status.blocked_nodes||[]);const t=status.checked_at?new Date(status.checked_at).toLocaleTimeString():'—';$('lastUpdate').textContent=`Updated ${t}`;$('updateDot').className='dot ok';}
function fail(msg){$('systemTop').textContent='ERROR';$('asteriskState').textContent='ERROR';$('appRptState').textContent='—';$('lastUpdate').textContent=msg||'Status failed';$('updateDot').className='dot bad';}
async function poll(){if(pollBusy)return;pollBusy=true;try{const r=await fetch('status.php',{cache:'no-store',credentials:'same-origin'}),s=await r.json();if(!r.ok||s.error)throw new Error(s.error||`HTTP ${r.status}`);apply(s);}catch(e){fail(e instanceof Error?e.message:String(e));}finally{pollBusy=false;}}
function positionHelpTip(btn){const tip=$('controlHelpTip');if(!tip)return;const text=btn.dataset.help||'';if(!text)return;tip.textContent=text;tip.hidden=false;tip.classList.add('show');tip.setAttribute('aria-hidden','false');const r=btn.getBoundingClientRect(),pad=8,maxW=Math.min(320,window.innerWidth-pad*2);tip.style.maxWidth=`${maxW}px`;tip.style.left='0px';tip.style.top='0px';const tr=tip.getBoundingClientRect();let left=r.left+r.width/2-tr.width/2;left=Math.max(pad,Math.min(left,window.innerWidth-tr.width-pad));let top=r.top-tr.height-8;if(top<pad)top=Math.min(window.innerHeight-tr.height-pad,r.bottom+8);tip.style.left=`${Math.round(left)}px`;tip.style.top=`${Math.round(top)}px`;}
function hideHelpTip(){const tip=$('controlHelpTip');if(!tip)return;tip.classList.remove('show');tip.hidden=true;tip.setAttribute('aria-hidden','true');document.querySelectorAll('.control-help.open').forEach(x=>x.classList.remove('open'));}
function initControlHelp(){document.querySelectorAll('.control-help').forEach(btn=>{btn.addEventListener('mouseenter',()=>positionHelpTip(btn));btn.addEventListener('mouseleave',()=>{if(!btn.classList.contains('open'))hideHelpTip();});btn.addEventListener('focus',()=>positionHelpTip(btn));btn.addEventListener('blur',()=>{if(!btn.classList.contains('open'))hideHelpTip();});btn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();const was=btn.classList.contains('open');document.querySelectorAll('.control-help.open').forEach(x=>x.classList.remove('open'));if(was){hideHelpTip();return;}btn.classList.add('open');positionHelpTip(btn);});});document.addEventListener('click',e=>{if(!e.target.closest('.control-help'))hideHelpTip();});window.addEventListener('resize',hideHelpTip);window.addEventListener('scroll',hideHelpTip,{passive:true});}
function setActionResult(kind,msg,detail='',boxId='actionResult'){const box=$(boxId)||$('actionResult');if(!box)return;box.hidden=false;box.className=`action-result ${kind||''}`;box.innerHTML=`<b>${esc(msg||'Action complete')}</b>${detail?`<small>${esc(detail)}</small>`:''}`;}
function setControlButtonsDisabled(disabled){document.querySelectorAll('.control-btn,.row-action').forEach(btn=>{btn.disabled=disabled||!canControl;});}
async function runAction(btn){if(actionBusy||!canControl)return;const action=btn.dataset.action||'',target=btn.dataset.target||'',boxId=btn.dataset.resultBox||'actionResult',confirmText=btn.dataset.confirm||'';if(confirmText&&!window.confirm(confirmText))return;let reason='';if(action==='block'){const entered=window.prompt('Optional block reason:','Blocked with ASL3 Node Manager');if(entered===null)return;reason=entered;}actionBusy=true;setControlButtonsDisabled(true);setActionResult('working','Working…','The node is being checked before and after the command.',boxId);try{const body=new URLSearchParams({action,csrf,target,reason}),r=await fetch('action.php',{method:'POST',body,credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'}}),data=await r.json(),kind=data.result==='verified'||data.result==='accepted'?'ok':data.result==='partial'?'warn':'bad';let detail='';if(Array.isArray(data.restored_links)&&data.restored_links.length)detail+=`Restored: ${data.restored_links.map(x=>x.node).join(', ')}. `;if(Array.isArray(data.failed_links)&&data.failed_links.length)detail+=`Needs attention: ${data.failed_links.map(x=>x.node).join(', ')}. `;if(Number.isInteger(data.remaining_links)&&data.remaining_links>0)detail+=`${data.remaining_links} connection(s) remain. `;if(Array.isArray(data.disconnect_failures)&&data.disconnect_failures.length)detail+=`Disconnect errors: ${data.disconnect_failures.map(x=>x.display||x.target||'?').join(', ')}.`;setActionResult(kind,data.message||'Action complete.',detail.trim(),boxId);await poll();}catch(e){setActionResult('bad','Control action failed.',e instanceof Error?e.message:String(e),boxId);}finally{actionBusy=false;setControlButtonsDisabled(false);}}

// Shared server-side appearance: Default/Advanced, separate Light/Dark profiles.
const DEFAULT_APPEARANCE={theme:'dark',mode:'default',profiles:{dark:{background:'#080E19',foreground:'#121D2F',text:'#F2F5FF',secondary:'#A9B9D4',headings:'#A9B9D4',accent:'#7458FF'},light:{background:'#EEF3FA',foreground:'#FFFFFF',text:'#142038',secondary:'#55657F',headings:'#55657F',accent:'#6550DD'}}};
let appearance=clone(window.ASL3_NODE_MANAGER_APPEARANCE||DEFAULT_APPEARANCE),pending=clone(appearance),editingField=null;
const customVars=['--bg','--panel','--text','--page-text','--muted','--secondary-text','--table-heading','--table-label','--primary','--focus'];
function applyAppearanceLocal(a){const root=document.documentElement;root.dataset.theme=a.theme;root.dataset.palette=a.mode;customVars.forEach(v=>root.style.removeProperty(v));if(a.mode==='advanced'){const p=a.profiles[a.theme];const map={'--bg':p.background,'--panel':p.foreground,'--text':p.text,'--page-text':p.text,'--muted':p.secondary,'--secondary-text':p.secondary,'--table-heading':p.headings,'--table-label':p.headings,'--primary':p.accent,'--focus':p.accent};Object.entries(map).forEach(([k,v])=>root.style.setProperty(k,v));}}
async function saveAppearance(next){if(!canControl)return false;const body=new URLSearchParams({action:'appearance',csrf,appearance:JSON.stringify(next)});const r=await fetch('action.php',{method:'POST',body,credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'}}),data=await r.json();if(!r.ok||!data.ok)throw new Error(data.message||'Appearance save failed.');appearance=clone(data.appearance||next);pending=clone(appearance);applyAppearanceLocal(appearance);return true;}
function colorProfile(){return pending.profiles[pending.theme];}
function drawColors(){const mode=$('colorMode');if(!mode)return;mode.value=pending.mode;$('advancedColorFields').hidden=pending.mode!=='advanced';const p=colorProfile();for(const k of ['background','foreground','text','secondary','headings','accent']){const sw=$(`swatch-${k}`),val=$(`value-${k}`);if(sw)sw.style.background=p[k];if(val)val.textContent=p[k];}$('colorMessage').textContent=`Editing ${pending.theme==='dark'?'Dark':'Light'} theme colors.`;}
function hexToRgb(hex){const n=parseInt(hex.slice(1),16);return[(n>>16)&255,(n>>8)&255,n&255];}
function rgbToHex(r,g,b){return '#'+[r,g,b].map(x=>Math.max(0,Math.min(255,Math.round(x))).toString(16).padStart(2,'0')).join('').toUpperCase();}
function hexToHsl(hex){let[r,g,b]=hexToRgb(hex).map(v=>v/255),max=Math.max(r,g,b),min=Math.min(r,g,b),h=0,s=0,l=(max+min)/2;if(max!==min){const d=max-min;s=l>.5?d/(2-max-min):d/(max+min);switch(max){case r:h=(g-b)/d+(g<b?6:0);break;case g:h=(b-r)/d+2;break;default:h=(r-g)/d+4;}h/=6;}return{h:Math.round(h*360),s:Math.round(s*100),l:Math.round(l*100)};}
function hslToHex(h,s,l){h=((Number(h)%360)+360)%360/360;s=Number(s)/100;l=Number(l)/100;if(s===0){const v=l*255;return rgbToHex(v,v,v);}const q=l<.5?l*(1+s):l+s-l*s,p=2*l-q,f=t=>{if(t<0)t+=1;if(t>1)t-=1;if(t<1/6)return p+(q-p)*6*t;if(t<1/2)return q;if(t<2/3)return p+(q-p)*(2/3-t)*6;return p;};return rgbToHex(f(h+1/3)*255,f(h)*255,f(h-1/3)*255);}
function setEditor(hex){const h=hexToHsl(hex);$('colorHue').value=h.h;$('colorSaturation').value=h.s;$('colorBrightness').value=h.l;$('colorHex').value=hex.toUpperCase();$('colorEditorPreview').style.background=hex;}
function sliderChanged(){const hex=hslToHex($('colorHue').value,$('colorSaturation').value,$('colorBrightness').value);$('colorHex').value=hex;$('colorEditorPreview').style.background=hex;}
function openEditor(field){editingField=field;const labels={background:'Background',foreground:'Foreground / Cards',text:'Text',secondary:'Secondary Text',headings:'Table Headings',accent:'Accent'};$('colorEditorTitle').textContent=`Choose ${labels[field]||'Color'}`;setEditor(colorProfile()[field]);$('colorMainPanel').hidden=true;$('colorEditor').hidden=false;}
function closeEditor(){$('colorEditor').hidden=true;$('colorMainPanel').hidden=false;editingField=null;}
function initAppearance(){applyAppearanceLocal(appearance);drawColors();$('themeToggle')?.addEventListener('click',async()=>{if(!canControl)return;const next=clone(appearance);next.theme=next.theme==='dark'?'light':'dark';try{await saveAppearance(next);drawColors();}catch(e){alert(e.message||String(e));}});$('colorMode')?.addEventListener('change',e=>{pending.mode=e.target.value==='advanced'?'advanced':'default';drawColors();});document.querySelectorAll('.advanced-color-button').forEach(btn=>btn.addEventListener('click',()=>openEditor(btn.dataset.colorTarget)));document.querySelectorAll('.quick-color-swatch').forEach(btn=>btn.addEventListener('click',()=>setEditor(btn.dataset.color)));['colorHue','colorSaturation','colorBrightness'].forEach(id=>$(id)?.addEventListener('input',sliderChanged));$('colorHex')?.addEventListener('input',()=>{const v=$('colorHex').value.trim().toUpperCase();if(/^#[0-9A-F]{6}$/.test(v))setEditor(v);});$('useColor')?.addEventListener('click',()=>{const hex=$('colorHex').value.trim().toUpperCase();if(editingField&&/^#[0-9A-F]{6}$/.test(hex)){pending.mode='advanced';if($('colorMode'))$('colorMode').value='advanced';colorProfile()[editingField]=hex;closeEditor();drawColors();}});$('cancelColor')?.addEventListener('click',closeEditor);$('resetColors')?.addEventListener('click',()=>{const theme=pending.theme;pending=clone(DEFAULT_APPEARANCE);pending.theme=theme;drawColors();});$('applyColors')?.addEventListener('click',async()=>{try{const mode=$('colorMode');pending.mode=mode&&mode.value==='advanced'?'advanced':'default';await saveAppearance(pending);drawColors();if($('colorMenu'))$('colorMenu').open=false;}catch(e){$('colorMessage').textContent=e.message||String(e);}});$('colorMenu')?.addEventListener('toggle',()=>{if($('colorMenu').open){pending=clone(appearance);drawColors();closeEditor();}});}

const mobileConnectionsToggle=$('mobileConnectionsToggle');
const mobileConnectionsContent=$('mobileConnectionsContent');
if(mobileConnectionsToggle&&mobileConnectionsContent){
  mobileConnectionsToggle.hidden=false;
  function setMobileConnectionsExpanded(expanded){
    mobileConnectionsContent.hidden=!expanded;
    mobileConnectionsToggle.textContent=expanded?'Hide':'Show';
    mobileConnectionsToggle.setAttribute('aria-expanded',String(expanded));
  }
  setMobileConnectionsExpanded(true);
  mobileConnectionsToggle.addEventListener('click',()=>{
    setMobileConnectionsExpanded(mobileConnectionsContent.hidden);
  });
}


function initServices(){
  const root=$('servicesPanel');if(!root)return;
  let favorites=[],editing='';let busy=false;let currentDialog=null;
  const svcDialogs=['svcFavoritesDialog','svcManagerDialog','svcOfficialDialog'];
  function closeDialog(){if(!currentDialog){document.body.classList.remove('svc-dialog-open');return;}const old=currentDialog;old.hidden=true;currentDialog=null;document.body.classList.remove('svc-dialog-open');const trigger=document.getElementById(old.dataset.trigger||'');if(trigger)trigger.focus();}
  function openDialog(id,trigger){closeDialog();const dlg=$(id);if(!dlg)return;dlg.dataset.trigger=trigger;dlg.hidden=false;currentDialog=dlg;document.body.classList.add('svc-dialog-open');dlg.querySelector('[data-svc-close]')?.focus();}
  for(const id of svcDialogs){const dlg=$(id);dlg.querySelector('[data-svc-close]')?.addEventListener('click',closeDialog);dlg.addEventListener('click',e=>{if(e.target===dlg)closeDialog();});}
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&currentDialog)closeDialog();});
  $('svcOpenFavorites').addEventListener('click',()=>openDialog('svcFavoritesDialog','svcOpenFavorites'));
  $('svcOpenManagerBackups').addEventListener('click',()=>{openDialog('svcManagerDialog','svcOpenManagerBackups');});
  $('svcOpenOfficialBackups').addEventListener('click',()=>{openDialog('svcOfficialDialog','svcOpenOfficialBackups');});
  $('svcActivityClear').addEventListener('click',()=>{const log=$('svcActivityLog');if(log)log.textContent='No operations in this session.';});
  $('svcFavoriteSort').addEventListener('change',renderFavorites);
  function renderFavorites(){const mode=$('svcFavoriteSort').value;const items=[...favorites];items.sort((a,b)=>mode==='alpha'?a.name.localeCompare(b.name,undefined,{sensitivity:'base'})||a.code.localeCompare(b.code):mode==='code'?a.code.localeCompare(b.code,undefined,{numeric:true}):a.code.localeCompare(b.code,undefined,{numeric:true})||a.name.localeCompare(b.name,undefined,{sensitivity:'base'}));$('svcFavoriteCount').textContent=`${items.length} saved`;
  $('svcFavorites').innerHTML=items.length?items.map(f=>`<div class="svc-row"><span><b>${esc(f.name)}</b><small>${esc(f.code)}</small></span><span class="svc-row-buttons"><button data-fav-load="${esc(f.code)}" title="Load into DTMF field; press Send separately">Load</button><button data-fav-edit="${esc(f.code)}" title="Edit saved Favorite">Edit</button><button data-fav-delete="${esc(f.code)}" title="Remove saved Favorite">Remove</button></span></div>`).join(''):'<div class="compact-note">No Favorites saved.</div>';}
  const safeCode=v=>String(v||'').replace(/[^0-9*#]/g,'').slice(0,14);
  const msg=(text,bad=false)=>{const e=$('svcResult');e.hidden=false;e.textContent=text;e.style.color=bad?'var(--red)':'var(--text)';
    const stamp=new Date().toLocaleString();const log=$('svcActivityLog');if(log&&text!=='Working…'){if(log.textContent==='No operations in this session.')log.textContent='';const item=document.createElement('div');item.className=bad?'svc-log-error':'svc-log-ok';item.textContent=`${stamp} — ${text}`;log.prepend(item);while(log.children.length>12)log.lastElementChild.remove();}
    const inModal=currentDialog?.id==='svcManagerDialog'?'svcManagerResult':currentDialog?.id==='svcOfficialDialog'?'svcOfficialResult':null;
    if(inModal){const el=$(inModal);if(el){el.hidden=false;el.textContent=text;el.className='svc-inline-result '+(bad?'is-error':'is-success');}}
  };
  async function req(action,fields={}){
    const body=new URLSearchParams({action,csrf,...fields});
    const r=await fetch('services.php',{method:'POST',body,credentials:'same-origin',cache:'no-store'});
    const d=await r.json();if(!r.ok||!d.ok)throw Error(d.message||'Services operation failed.');return d;
  }
  function showManagerBackups(items){
    $('svcBackupCount').textContent=String(items.length);
    $('svcBackups').innerHTML=items.length?items.map(b=>`<div class="svc-row"><span><b>${esc(b.name)}</b><small>${(b.bytes/1024).toFixed(1)} KB</small></span><span class="svc-row-buttons"><button data-backup-verify="${esc(b.name)}" title="Verify the archive in /var/backups/asl3-node-manager/asl3-config/ without changing the node.">Verify</button><button data-backup-download="${esc(b.name)}" title="Download this archive from /var/backups/asl3-node-manager/asl3-config/ to your browser Downloads folder or configured download location.">Download</button><button class="svc-restore-danger" data-restore-live="${esc(b.name)}" title="Restore from /var/backups/asl3-node-manager/asl3-config/. Replaces current supported files; newer changes may be lost. Creates a safety backup and restarts Asterisk.">Restore</button><button class="svc-restore-danger" data-backup-delete="${esc(b.name)}" title="Permanently delete this archive from /var/backups/asl3-node-manager/asl3-config/. Cannot be undone.">Delete</button></span></div>`).join(''):'<div class="compact-note">No configuration backups yet.</div>';
  }
  async function refresh(){if(!canControl)return;try{const d=await req('list');favorites=d.favorites||[];
    $('svcAsterisk').textContent=d.services?.asterisk||'unknown';$('svcApache').textContent=d.services?.apache2||'unknown';
    renderFavorites();
    $('svcBackupCount').textContent=String((d.backups||[]).length);
    $('svcOfficialBackupCount').textContent=String((d.official_backups||[]).length);
    showManagerBackups(d.backups||[]);
    showOfficialBackups(d.official_backups||[]);
  }catch(e){msg(e.message,true);}}
  function showOfficialBackups(items){
    $('svcOfficialBackupCount').textContent=String(items.length);
    $('svcOfficialBackups').innerHTML=items.length?items.map(b=>`<div class="svc-row"><span><b>${esc(b.name)}</b><small>${(b.bytes/1024).toFixed(1)} KB · official ASL3</small></span><span class="svc-row-buttons"><button data-official-verify="${esc(b.name)}" title="Verify the archive in /var/asl-backups/ without changing the node.">Verify</button><button data-official-download="${esc(b.name)}" title="Download this archive from /var/asl-backups/ to your browser Downloads folder or configured download location.">Download</button><button class="svc-restore-danger" data-official-live="${esc(b.name)}" title="Restore from /var/asl-backups/. Replaces current supported files; newer changes may be lost. Creates a safety backup and restarts Asterisk.">Restore</button><button class="svc-restore-danger" data-official-delete="${esc(b.name)}" title="Permanently delete this archive from /var/asl-backups/. Also removes it from the asl-menu backup list. Cannot be undone.">Delete</button></span></div>`).join(''):'<div class="compact-note">No official ASL3 backup archives found.</div>';
  }
  async function run(action,fields={}){if(busy||!canControl)return;busy=true;root.querySelectorAll('button:not([data-svc-close])').forEach(b=>b.disabled=true);
    msg('Working…');let ok=false;try{const d=await req(action,fields);ok=true;msg(d.message||'Completed.');if(Array.isArray(d.backups))showManagerBackups(d.backups);if(Array.isArray(d.official_backups))showOfficialBackups(d.official_backups);await refresh();}catch(e){msg(e.message,true);}finally{busy=false;root.querySelectorAll('button:not([data-svc-close])').forEach(b=>b.disabled=!canControl);}return ok;}
  root.querySelectorAll('button:not([data-svc-close])').forEach(b=>b.disabled=!canControl);
  $('svcDtmfCode').addEventListener('input',e=>e.target.value=safeCode(e.target.value));
  $('svcFavCode').addEventListener('input',e=>e.target.value=safeCode(e.target.value));
  $('svcDtmfSend').addEventListener('click',async()=>{const code=safeCode($('svcDtmfCode').value);if(!code)return msg('Enter a complete DTMF command (for example *921).',true);if(await run('dtmf-send',{code})){$('svcDtmfCode').value='';msg(`DTMF ${code} submitted to Asterisk; function execution is not confirmed.`);}});
  $('svcFavSave').addEventListener('click',async()=>{const code=safeCode($('svcFavCode').value),name=$('svcFavName').value.trim();if(!code)return msg('Enter a Favorite code.',true);if(!await run('favorite-save',{code,name,original_code:editing}))return;editing='';$('svcFavCode').value='';$('svcFavName').value='';$('svcFavSave').textContent='Add Favorite';$('svcFavCancel').hidden=true;});
  $('svcFavCancel').addEventListener('click',()=>{editing='';$('svcFavCode').value='';$('svcFavName').value='';$('svcFavSave').textContent='Add Favorite';$('svcFavCancel').hidden=true;});
  $('svcFavorites').addEventListener('click',e=>{const b=e.target.closest('button');if(!b||!canControl)return;const code=b.dataset.favLoad||b.dataset.favEdit||b.dataset.favDelete||'';
    if(b.dataset.favLoad){$('svcDtmfCode').value=code;closeDialog();$('svcDtmfCode').focus();msg(`Loaded ${code}. Press Send to transmit.`);}
    else if(b.dataset.favEdit){const f=favorites.find(x=>x.code===code);if(f){editing=code;$('svcFavCode').value=f.code;$('svcFavName').value=f.name;$('svcFavSave').textContent='Save Changes';$('svcFavCancel').hidden=false;}}
    else if(b.dataset.favDelete&&confirm(`Remove DTMF Favorite ${code}?`))run('favorite-delete',{code});});
  $('svcBackupCreate').addEventListener('click',()=>{if(confirm('Create a local ASL3 configuration backup now? Live databases may change while being archived.'))run('backup-create');});
  let restoreReturnDialog='';
  function closeRestoreConfirm(returnToList=false){
    const dlg=$('svcRestoreConfirm');
    dlg.hidden=true;
    const returnId=restoreReturnDialog;
    restoreReturnDialog='';
    if(returnToList&&returnId){
      openDialog(returnId,returnId==='svcManagerDialog'?'svcOpenManagerBackups':'svcOpenOfficialBackups');
    }else{
      document.body.classList.remove('svc-dialog-open');
    }
  }
  async function confirmLiveRestore(source,name){
    if(busy||!canControl)return;
    const dlg=$('svcRestoreConfirm'),description=$('svcRestoreDescription');
    restoreReturnDialog=source==='official'?'svcOfficialDialog':'svcManagerDialog';
    // Only one modal can own the overlay and focus at a time.
    closeDialog();
    $('svcRestoreArchive').textContent=name;
    description.textContent=source==='official'?'Restore all supported files from this official ASL3 archive, including Allmon3 configuration (without enabling Allmon3).':'Restore the Asterisk configuration and data saved in this Node Manager archive.';
    $('svcRestoreSource').value=source;$('svcRestoreName').value=name;
    dlg.hidden=false;
    document.body.classList.add('svc-dialog-open');
    $('svcRestoreCancel').focus();
  }
  $('svcRestoreCancel').addEventListener('click',()=>closeRestoreConfirm(true));
  $('svcRestoreConfirm').addEventListener('click',e=>{if(e.target===$('svcRestoreConfirm'))closeRestoreConfirm(true);});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('svcRestoreConfirm').hidden){e.preventDefault();closeRestoreConfirm(true);}});
  $('svcRestoreProceed').addEventListener('click',async()=>{const source=$('svcRestoreSource').value,name=$('svcRestoreName').value;closeRestoreConfirm(false);await run('restore-live',{source,backup_name:name,confirmation:'RESTORE'});});
  function downloadBackup(name,source){
    const form=document.createElement('form');
    form.method='POST';
    form.action='backup_download.php';
    form.hidden=true;
    for(const [key,value] of Object.entries({name,source,csrf})){
      const field=document.createElement('input');
      field.name=key;
      field.value=value;
      form.appendChild(field);
    }
    document.body.appendChild(form);
    form.submit();
    form.remove();
    msg(`Download requested: ${name}. Check your browser's Downloads folder or configured download location.`);
  }
  $('svcOfficialBackups').addEventListener('click',e=>{const b=e.target.closest('button');if(b?.dataset.officialVerify)run('official-backup-verify',{backup_name:b.dataset.officialVerify});if(b?.dataset.officialDownload&&canControl)downloadBackup(b.dataset.officialDownload,'official');if(b?.dataset.officialLive)confirmLiveRestore('official',b.dataset.officialLive);if(b?.dataset.officialDelete&&confirm(`Permanently delete official ASL3 backup ${b.dataset.officialDelete}? This cannot be undone. This file will also disappear from asl-menu.`))run('official-backup-delete',{backup_name:b.dataset.officialDelete});});
  $('svcBackups').addEventListener('click',e=>{const b=e.target.closest('button');if(b?.dataset.backupVerify)run('backup-verify',{backup_name:b.dataset.backupVerify});if(b?.dataset.backupDelete&&confirm(`Permanently delete Node Manager backup ${b.dataset.backupDelete}? This cannot be undone.`))run('backup-delete',{backup_name:b.dataset.backupDelete});if(b?.dataset.restoreLive)confirmLiveRestore('manager',b.dataset.restoreLive);if(b?.dataset.backupDownload&&canControl)downloadBackup(b.dataset.backupDownload,'manager');});
  root.querySelectorAll('[data-service]').forEach(b=>b.addEventListener('click',()=>{const a=b.dataset.service;const warnings={'asterisk-restart':'All active calls and links will disconnect.','apache-restart':'The web dashboard may temporarily disconnect.','app-rpt-reload':'Repeater operation and connected links may be briefly affected.','asterisk-reload':'Active calls and links may be affected.','apache-reload':'Active web requests may be briefly affected.'};if(confirm(`${b.textContent.trim()}? ${warnings[a]||'This may affect active sessions.'}`))run(a);}));
  if(canControl)refresh();
}

const sectionStorageKey='asl3-node-manager-active-section';
const validSections=['statusPanel','linksPanel','controlsPanel','servicesPanel'];

function selectSection(panelId){
  if(!validSections.includes(panelId))panelId='statusPanel';
  document.querySelectorAll('.section-tab').forEach(btn=>{
    btn.classList.toggle('active',btn.dataset.mobilePanel===panelId);
  });
  document.querySelectorAll('.mobile-panel').forEach(panel=>{
    panel.classList.toggle('active',panel.id===panelId);
  });
}

document.querySelectorAll('.section-tab').forEach(btn=>{
  btn.addEventListener('click',()=>{
    const panelId=btn.dataset.mobilePanel;
    selectSection(panelId);
    try{localStorage.setItem(sectionStorageKey,panelId);}catch(_){}
  });
});

try{
  selectSection(localStorage.getItem(sectionStorageKey)||'statusPanel');
}catch(_){
  selectSection('statusPanel');
}
document.addEventListener('click',e=>{const btn=e.target.closest('.control-btn,.row-action');if(btn)runAction(btn);});
initServices();initControlHelp();initAppearance();setControlButtonsDisabled(false);checkForUpdate();poll();setInterval(poll,1000);
})();
