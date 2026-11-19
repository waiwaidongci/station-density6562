import hashlib,json,threading
from datetime import date
from fastapi import HTTPException
from sqlalchemy import select,text
from sqlalchemy.exc import IntegrityError
from ..models.visit import VisitDayQuota,VisitRoster,VisitRosterItem,VisitReservationLock
from ..utils.serialization import row,now
from .runs import get_run
from .audit import log
from .visit_sampling import build_candidates,solve_assignment,group_eligible_counts,suggest_counts
RESERVATION_LOCK=threading.Lock()


def _iso(day):
    try:value=date.fromisoformat(str(day))
    except (TypeError,ValueError):raise HTTPException(422,'可访日期需为 YYYY-MM-DD 格式')
    return value.isoformat()

def list_quotas(db):
    quotas=[row(q) for q in db.scalars(select(VisitDayQuota).order_by(VisitDayQuota.day))]
    used=used_slots(db,[q['day'] for q in quotas]) if quotas else {}
    for q in quotas:
        q['used']=used.get(q['day'],0)
        q['remaining']=max(0,int(q['capacity'])-q['used'])
    return quotas

def set_quotas(db,user,data):
    cleaned=[]
    for quota in data.quotas:
        day=_iso(quota.day)
        if any(item['day']==day for item in cleaned):raise HTTPException(422,'同一天名额只能提交一次：'+day)
        cleaned.append({'day':day,'capacity':int(quota.capacity)})
    used=used_slots(db,[item['day'] for item in cleaned])
    for item in cleaned:
        if item['capacity']<used.get(item['day'],0):raise HTTPException(409,'该日已有 '+str(used[item['day']])+' 个名单占位，名额不能低于已用数：'+item['day'])
    for item in cleaned:
        current=db.get(VisitDayQuota,item['day'])
        if current:current.capacity=item['capacity']
        else:db.add(VisitDayQuota(day=item['day'],capacity=item['capacity']))
    log(db,user,'visit.quotas.updated',','.join(item['day'] for item in cleaned),json.dumps({item['day']:item['capacity'] for item in cleaned},ensure_ascii=False))
    db.commit()
    return list_quotas(db)

def quota_map(db,days):
    rows=db.scalars(select(VisitDayQuota).where(VisitDayQuota.day.in_(days)).order_by(VisitDayQuota.day)).all()
    return {q.day:int(q.capacity) for q in rows}

def used_slots(db,days):
    used={day:0 for day in days}
    for day in db.scalars(select(VisitRosterItem.day).where(VisitRosterItem.day.in_(days))).all():
        used[day]=used.get(day,0)+1
    return used

def _request_hash(run_id,counts,days,availability):
    canonical={'run_id':run_id,'counts':{str(k):int(v) for k,v in sorted(counts.items())},'days':list(days),'availability':{k:sorted(v) for k,v in sorted(availability.items())}}
    return hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def _load_roster(db,roster):
    items=[row(i) for i in db.scalars(select(VisitRosterItem).where(VisitRosterItem.roster_id==roster.id).order_by(VisitRosterItem.day,VisitRosterItem.cluster,VisitRosterItem.reference))]
    data=row(roster);data['items']=items
    return data

def get_roster(db,id):
    roster=db.get(VisitRoster,id)
    if not roster:raise HTTPException(404,'未找到抽样名单')
    return _load_roster(db,roster)

def list_rosters(db,run_id=None):
    statement=select(VisitRoster).order_by(VisitRoster.id.desc())
    if run_id is not None:statement=statement.where(VisitRoster.run_id==run_id)
    out=[]
    for roster in db.scalars(statement):
        data=row(roster)
        data['items']=[row(i) for i in db.scalars(select(VisitRosterItem).where(VisitRosterItem.roster_id==roster.id).order_by(VisitRosterItem.day,VisitRosterItem.cluster,VisitRosterItem.reference))]
        out.append(data)
    return out

def _normalize_counts(counts,groups):
    normalized={}
    for key,value in counts.items():
        try:cluster=int(key)
        except (TypeError,ValueError):raise HTTPException(422,'抽样分区编号必须为整数：'+str(key))
        if isinstance(value,bool):raise HTTPException(422,'每个分区的抽样数必须为整数')
        try:
            numeric=float(value)
        except (TypeError,ValueError):raise HTTPException(422,'每个分区的抽样数必须为整数')
        if not numeric.is_integer():raise HTTPException(422,'每个分区的抽样数必须为整数')
        value=int(numeric)
        if value<0:raise HTTPException(422,'每个分区的抽样数不能为负')
        if value and cluster not in groups:raise HTTPException(422,'该研究没有'+(('噪声组' if cluster<0 else '分区 '+str(cluster)))+'，不能指定抽样数')
        if value:normalized[cluster]=normalized.get(cluster,0)+value
    return normalized

def _normalize_days(days):
    cleaned=[];seen=set()
    for day in days:
        value=_iso(day)
        if value in seen:raise HTTPException(422,'可访日期不能重复：'+value)
        seen.add(value);cleaned.append(value)
    if not cleaned:raise HTTPException(422,'至少需要一个可访日期')
    return cleaned

def _normalize_availability(availability,days,references):
    allowed=set(days);out={}
    for reference,choices in availability.items():
        if reference not in references:raise HTTPException(422,'可访日中的样本不属于该研究：'+reference)
        if not isinstance(choices,list) or not choices:raise HTTPException(422,'样本可访日必须至少包含一天：'+reference)
        picked=[]
        for day in choices:
            value=_iso(day)
            if value not in allowed:raise HTTPException(422,'样本可访日不在本次抽样日期内：'+reference+' / '+value)
            if value not in picked:picked.append(value)
        out[reference]=picked
    return out

def _shortage_message(missing,eligible_by_group,requested,capacity,used,days):
    parts=[]
    for cluster in sorted(missing):
        if missing[cluster]<=0:continue
        label='噪声组' if cluster<0 else '分区 '+str(cluster)
        parts.append(label+' 需 '+str(requested[cluster])+'，按现有可访站与名额只能安排 '+str(requested[cluster]-missing[cluster])+'（可访候选 '+str(eligible_by_group.get(cluster,0))+'）')
    free=sum(max(0,capacity.get(day,0)-used.get(day,0)) for day in days)
    unset=[day for day in days if day not in capacity]
    note=('以下日期尚未设置名额：'+'、'.join(unset)+'。') if unset else ''
    return '名额不足，整单未占位：'+'；'.join(parts)+'。'+note+'当前剩余每日名额合计 '+str(free)+'。请减少抽样数，或补充每日名额与站点可访日。'

def ensure_reservation_lock(db):
    db.execute(text("INSERT INTO visit_reservation_locks (purpose) VALUES ('visit-roster') ON CONFLICT (purpose) DO NOTHING"))
    db.commit()

def _lock_reservations(db):
    db.execute(text("INSERT INTO visit_reservation_locks (purpose) VALUES ('visit-roster') ON CONFLICT (purpose) DO NOTHING"))
    db.scalar(select(VisitReservationLock).where(VisitReservationLock.purpose=='visit-roster').with_for_update())

def create_roster(db,user,data):
    run=get_run(db,data.run_id)
    if run.state!='completed':raise HTTPException(409,'只可从已完成研究发起取样')
    result=run.result or {}
    try:groups,centers=build_candidates(result.get('rows',[]),result.get('clusters',[]),(result.get('standardization') or {}).get('mean',[]),(result.get('standardization') or {}).get('scale',[]))
    except ValueError as error:raise HTTPException(422,str(error))
    if not groups:raise HTTPException(422,'该研究结果没有可抽样站点')
    counts=_normalize_counts(data.counts,groups)
    if not counts:raise HTTPException(422,'至少为一个分区指定大于0的抽样数')
    for cluster,value in counts.items():
        if value>len(groups[cluster]):raise HTTPException(422,('噪声组' if cluster<0 else '分区 '+str(cluster))+' 只有 '+str(len(groups[cluster]))+' 个可抽样站点，不能抽取 '+str(value)+' 个')
    days=_normalize_days(data.days)
    references={item['reference'] for candidates in groups.values() for item in candidates}
    availability=_normalize_availability(data.availability,days,references)
    request_hash=_request_hash(run.id,counts,days,availability)
    with RESERVATION_LOCK:
        existing=db.scalar(select(VisitRoster).where(VisitRoster.request_key==data.request_key))
        if existing:
            if existing.request_hash!=request_hash:raise HTTPException(409,'该请求编号已用于不同的抽样输入，请换一个请求编号')
            return _load_roster(db,existing)
        _lock_reservations(db)
        capacity=quota_map(db,days)
        used=used_slots(db,days)
        remaining={day:max(0,capacity.get(day,0)-used.get(day,0)) for day in days}
        try:solution=solve_assignment(counts,groups,days,availability,remaining)
        except ValueError as error:raise HTTPException(422,str(error))
        if any(value>0 for value in solution['missing'].values()):
            eligible=group_eligible_counts(groups,days,availability,remaining)
            raise HTTPException(409,_shortage_message(solution['missing'],eligible,counts,capacity,used,days))
        roster=VisitRoster(run_id=run.id,name=data.name,request_key=data.request_key,request_hash=request_hash,state='reserved',summary={},created_by=user.email,created_at=now())
        db.add(roster);db.flush()
        items=[VisitRosterItem(roster_id=roster.id,reference=item['reference'],cluster=item['cluster'],kind=item['kind'],distance=float(item['distance']),day=item['day']) for item in solution['items']]
        db.add_all(items)
        by_day={day:sum(1 for item in solution['items'] if item['day']==day) for day in days}
        roster.summary={'total_selected':len(items),'total_distance':solution['total_distance'],'days':days,'requested':{str(k):v for k,v in counts.items()},'by_cluster':{str(cluster):sum(1 for item in solution['items'] if item['cluster']==cluster) for cluster in counts},'by_day':by_day,'capacity':{day:capacity.get(day,0) for day in days},'used_before':{day:used.get(day,0) for day in days},'remaining_after':{day:remaining[day]-by_day[day] for day in days}}
        log(db,user,'visit.roster.reserved',roster.id,data.name+' · '+str(len(items))+' 站')
        try:db.commit()
        except IntegrityError:
            db.rollback()
            existing=db.scalar(select(VisitRoster).where(VisitRoster.request_key==data.request_key))
            if existing and existing.request_hash==request_hash:return _load_roster(db,existing)
            raise HTTPException(409,'并发写入冲突，请重试')
        return get_roster(db,roster.id)

def suggest_counts_for_run(db,run_id,total):
    run=get_run(db,run_id)
    if run.state!='completed':raise HTTPException(409,'只可从已完成研究发起取样')
    result=run.result or {}
    try:groups,_=build_candidates(result.get('rows',[]),result.get('clusters',[]),(result.get('standardization') or {}).get('mean',[]),(result.get('standardization') or {}).get('scale',[]))
    except ValueError as error:raise HTTPException(422,str(error))
    if not groups:raise HTTPException(422,'该研究结果没有可抽样站点')
    return {'total':int(total),'counts':suggest_counts(groups,total),'sizes':{str(cluster):len(items) for cluster,items in sorted(groups.items())}}
