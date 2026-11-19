import csv,io
from sqlalchemy import select
from fastapi import HTTPException
from fastapi.responses import Response
from ..models.note import Note
from ..models.visit import VisitRoster,VisitRosterItem
from .runs import get_run
def csv_response(result,filename):
    buf=io.StringIO();fields=result['columns'];w=csv.DictWriter(buf,fieldnames=fields);w.writeheader()
    for r in result['rows']:w.writerow({k:r.get(k,'') for k in fields})
    return Response('﻿'+buf.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="'+filename+'"'})
def run_csv(db,id):
    r=get_run(db,id)
    if r.state!='completed':raise HTTPException(409,'结果尚未完成')
    return csv_response(r.result,'run-'+str(id)+'.csv')
def note_csv(db,id):
    n=db.get(Note,id)
    if not n:raise HTTPException(404,'未找到说明')
    if n.state!='approved':raise HTTPException(403,'仅批准后的业务说明可导出')
    return csv_response(n.frozen_result,'approved-'+str(id)+'.csv')

def roster_csv(db,id):
    roster=db.get(VisitRoster,id)
    if not roster:raise HTTPException(404,'未找到抽样名单')
    items=db.scalars(select(VisitRosterItem).where(VisitRosterItem.roster_id==roster.id).order_by(VisitRosterItem.day,VisitRosterItem.cluster,VisitRosterItem.reference)).all()
    buf=io.StringIO();w=csv.writer(buf);w.writerow(['day','cluster','reference','kind','distance'])
    for item in items:w.writerow([item.day,item.cluster,item.reference,item.kind,round(item.distance,6)])
    return Response('\ufeff'+buf.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="visit-roster-'+str(id)+'.csv"'})
