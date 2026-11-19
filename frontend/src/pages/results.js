import {domain} from '../constants/domain.js';
import {research} from '../stores/research.js';
import {runsApi,visitApi} from '../api/research.js';
import {download} from '../api/client.js';
import {runOptions,metrics} from '../components/common/business.js';
import {status} from '../components/common/status.js';
import {bars} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {diagnostics} from './domain_result.js';
import {visitPanel,bindVisit,defaultDays} from './visit.js';
import {esc} from '../utils/format.js';
import {bind,toast} from '../hooks/actions.js';

async function visitSection(run,result){
  if(run.state!=='completed')return '';
  try{
    const [rosters,quotas]=await Promise.all([visitApi.rosters(run.id),visitApi.quotas()]);
    const days=defaultDays();
    const free=quotas.filter(q=>days.includes(q.day)).reduce((sum,q)=>sum+q.remaining,0);
    const total=Math.min(12,Math.max(1,free||6));
    let suggestion;
    try{suggestion=await visitApi.suggest(run.id,total)}
    catch{const sizes={};for(const row of result.rows)sizes[row.cluster]=(sizes[row.cluster]||0)+1;const population=Object.values(sizes).reduce((a,b)=>a+b,0)||1;const counts={};for(const cluster of Object.keys(sizes))counts[cluster]=Math.max(1,Math.round(sizes[cluster]*total/population));suggestion={total,sizes,counts}}
    return visitPanel({result,runId:run.id,rosters,quotas,suggestion});
  }catch(error){
    return '<section class="visit-section"><h2>复访抽样与名额占位</h2><p class="failure">抽样信息暂时无法读取：'+esc(error.message)+'</p></section>';
  }
}

export async function resultsPage(){
  const run=research.runId?await runsApi.get(research.runId):null;research.activeRun=run;const result=run?.result;
  const heading='<section class="page-heading"><p class="eyebrow">04 / RESULT & INTERPRETATION</p><h1>'+esc(domain.result_headline)+'</h1><p>读取创建时冻结的来源、参数与样本，研究结果可以独立导出复算；复核后可在此按分区抽取复访代表站。</p></section><label class="compact">结果任务<select id="run-select">'+runOptions(research.runs,research.runId)+'</select></label>';
  if(!run)return heading+'<p class="empty">还没有任务，请先创建来源并执行一轮分析。</p>';
  const title='<div class="run-title"><h2>'+esc(run.name)+'</h2>'+status(run.state)+'<small>#'+run.id+' · 来源 #'+run.source_id+'</small>'+(run.state==='completed'?'<button id="export-run" class="secondary">下载结果 CSV ↗</button>':'')+'</div><p class="fine">参数：'+esc(JSON.stringify(run.parameters))+' · 冻结 '+run.snapshot.records.length+' 条输入 · '+esc(run.snapshot.source.filename)+'</p>';
  let body;
  if(run.state==='failed')body='<div class="failure"><h2>本次计算未完成</h2><p>'+esc(run.error)+'</p><a href="#source">核对输入</a> · <a href="#config">修正参数后重新执行</a></div>';
  else if(!result)body='<div class="pending"><span class="spinner"></span><h2>独立 worker 正在处理</h2><p>页面自动刷新状态。可以返回其他模块，队列计算会继续。</p></div>';
  else body=metrics(result.summary)+'<div class="result-grid"><section><h2>业务结构</h2>'+bars(result.chart)+'</section><aside class="method-sheet"><p class="eyebrow">READING NOTES</p><p>'+esc(result.explanation)+'</p><small>随机种子 '+result.seed+' · 输入 SHA256<br><code>'+esc(result.checksum)+'</code></small></aside></div>'+diagnostics(result)+'<h2>完整计算明细 <small>共 '+result.rows.length+' 行，预览前30行；CSV含全部行</small></h2>'+table(result.rows,result.columns.map(c=>({key:c,label:domain.column_labels[c]||c})),{limit:30})+'<p><a class="text-link" href="#notes">据此提交业务说明 ↗</a></p>'+await visitSection(run,result);
  return heading+title+body;
}

export function bindResults(refresh){
  bind('#run-select','change',async e=>{research.runId=Number(e.target.value);await refresh()});
  bind('#export-run','click',async()=>{try{await download('/runs/'+research.runId+'/export','research-'+research.runId+'.csv')}catch(e){toast(e.message,true)}});
  bindVisit(refresh);
}
