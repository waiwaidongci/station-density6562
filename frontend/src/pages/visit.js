import {domain} from '../constants/domain.js';
import {session} from '../stores/session.js';
import {visitApi} from '../api/research.js';
import {download} from '../api/client.js';
import {esc,fmt} from '../utils/format.js';
import {table} from '../components/common/table.js';
import {toast} from '../hooks/actions.js';

const clusterLabel=cluster=>Number(cluster)<0?'噪声组':'分区 '+cluster;
const round=value=>Number(Number(value).toFixed(4));
const shanghaiDate=offset=>{const d=new Date();d.setUTCDate(d.getUTCDate()+offset);return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(d)}
export function defaultDays(){return [shanghaiDate(1),shanghaiDate(2)]}

function quotaEditor(quotas){
  const summary=quotas.length?'<p class="fine">'+quotas.map(q=>esc(q.day)+' 已用 '+q.used+' / '+q.capacity+'，剩余 '+q.remaining).join('；')+'</p>':'<p class="fine">尚未设置每日名额；没有名额时无法占位。</p>';
  if(session.user?.role!=='admin')return '<details><summary>每日名额（各研究共用）</summary>'+summary+'<p class="fine">名额由负责人维护。</p></details>';
  return '<details id="quota-editor"><summary>每日名额（各研究共用）</summary>'+summary+'<form id="quota-form"><div class="parameter-fields"><label>日期<input name="day" type="date" required value="'+shanghaiDate(1)+'"></label><label>当日名额<input name="capacity" type="number" min="0" max="1000" step="1" required value="8"></label></div><button type="submit">设置该日名额 →</button></form></details>'
}

function rosterList(rosters){
  if(!rosters.length)return '<p class="empty">还没有抽样名单。核对名称、分区抽样数与可访日后生成第一张名单。</p>';
  return rosters.map(roster=>'<article class="roster-record"><header><span class="status reserved">已占位</span><small>研究 #'+roster.run_id+' · '+esc(roster.created_by)+'</small></header><h2>'+esc(roster.name)+'</h2><p class="fine">共 '+roster.summary.total_selected+' 站 · 到组中心标准化距离合计 '+fmt(round(roster.summary.total_distance))+' · '+esc(roster.summary.days.map(day=>day+' '+roster.summary.by_day[day]+' 站').join(' / '))+'</p>'+table(roster.items.map(item=>({...item,cluster:clusterLabel(item.cluster),distance:round(item.distance)})),[{key:'day',label:'可访日'},{key:'cluster',label:'所属组'},{key:'reference',label:'样本编号'},{key:'kind',label:'微站类型'},{key:'distance',label:'标准化距离'}],{limit:200})+'<footer><small>请求编号 '+esc(roster.request_key)+'</small><button class="secondary" data-roster-export="'+roster.id+'">下载名单 CSV ↗</button></footer></article>').join('')
}

export function visitPanel({result,runId,rosters,quotas,suggestion}){
  const sizes=suggestion.sizes,counts=suggestion.counts;
  const groups=Object.keys(sizes).map(Number).sort((a,b)=>a-b);
  const writable=session.writable;
  const form=writable?'<form id="sample-form" class="sample-form" data-run-id="'+runId+'"><h2>发起取样</h2><label>名单名称<input name="name" required value="'+esc(domain.note)+' · '+shanghaiDate(0)+'"></label><div class="sample-groups">'+groups.map(cluster=>'<label>'+clusterLabel(cluster)+'<small data-group-size="'+cluster+'" data-size="'+sizes[cluster]+'"> / 共 '+sizes[cluster]+' 站</small><input type="number" min="0" max="'+sizes[cluster]+'" step="1" name="count-'+cluster+'" value="'+counts[cluster]+'"></label>').join('')+'</div><label>可访日期<small> 逗号分隔，格式 YYYY-MM-DD；每日名额由所有研究共用</small><input name="days" required value="'+defaultDays().join(',')+'"></label><label>站点可访日覆盖<small> 可选，每行 reference=日期1,日期2；未列出的站点视为全部可访日</small><textarea name="availability" rows="3" placeholder="'+esc(domain.code)+'-202611-01-0001=2026-11-21"></textarea></label><p class="fine">提交后按剩余名额重算；名额或可访日不足时整单不写入、不占位，并说明缺额。重试同一名单不会重复占位。</p><button type="submit">生成名单并占位 →</button></form>':'<div class="method-note"><b>只读</b><p>抽样名单由分析师或负责人发起；你可以查看名单与导出。</p></div>';
  return '<section class="visit-section"><h2>复访抽样与名额占位 <small>从已完成研究按分区与噪声组抽样</small></h2><p class="fine">抽样数按各组站点规模填写，系统在分区配额、每日名额与站点可访日约束下，选择使入选站到各自组中心标准化距离总和最小的组合；一张名单内每站只排一次。</p><div class="visit-grid">'+form+'<div class="roster-column"><h2>已有名单</h2>'+rosterList(rosters)+quotaEditor(quotas)+'</div></div></section>';
}

function parseAvailability(text){
  const out={};
  for(const line of text.split('\n')){
    const trimmed=line.trim();if(!trimmed)continue;
    const index=trimmed.indexOf('=');
    if(index<=0)throw Error('站点可访日格式应为 reference=日期1,日期2');
    const reference=trimmed.slice(0,index).trim();
    const days=trimmed.slice(index+1).split(',').map(day=>day.trim()).filter(Boolean);
    if(!reference||!days.length)throw Error('站点可访日格式应为 reference=日期1,日期2');
    out[reference]=days;
  }
  return out;
}

function newRequestKey(){return 'visit-'+(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10))}
let requestKey=newRequestKey();

export function bindVisit(refresh){
  const form=document.querySelector('#sample-form');
  if(form)form.onsubmit=async event=>{
    event.preventDefault();const button=form.querySelector('button[type="submit"]');if(button)button.disabled=true;
    try{
      const data=Object.fromEntries(new FormData(form));const counts={};
      for(const key of Object.keys(data))if(key.startsWith('count-'))counts[key.slice(6)]=Number(data[key]);
      await visitApi.create({run_id:Number(form.dataset.runId),name:data.name,request_key:requestKey,counts,days:data.days.split(',').map(day=>day.trim()).filter(Boolean),availability:parseAvailability(data.availability||'')});
      await refresh();
      requestKey=newRequestKey();toast('名单已生成并占用名额');
    }catch(error){toast(error.message,true)}finally{if(button)button.disabled=false}
  };
  const quotaForm=document.querySelector('#quota-form');
  if(quotaForm)quotaForm.onsubmit=async event=>{
    event.preventDefault();const data=Object.fromEntries(new FormData(quotaForm));
    try{await visitApi.setQuotas([{day:data.day,capacity:Number(data.capacity)}]);await refresh();toast('每日名额已更新')}catch(error){toast(error.message,true)}
  };
  for(const b of document.querySelectorAll('[data-roster-export]'))b.onclick=async()=>{try{await download('/visit-rosters/'+b.dataset.rosterExport+'/export','visit-roster-'+b.dataset.rosterExport+'.csv')}catch(e){toast(e.message,true)}};
  const sampleForm=document.querySelector('#sample-form');
  if(sampleForm)for(const input of sampleForm.querySelectorAll('input[type=number]'))input.oninput=()=>{
    const cluster=input.name.slice(6),hint=sampleForm.querySelector('[data-group-size="'+cluster+'"]');
    if(!hint)return;const size=Number(hint.dataset.size||0);
    if(Number(input.value)>size){input.value=size;toast('抽样数不能超过该组站点数（共 '+size+' 站）',true)}
  };
}
