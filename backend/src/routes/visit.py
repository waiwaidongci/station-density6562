from fastapi import APIRouter,Depends,Query,HTTPException
from ..config.database import db_session
from ..schemas.visit import SamplingInput,QuotaBatch
from ..services.auth import current_user,writer
from ..services.runs import get_run
from ..services.visit_sampling import build_candidates
from ..controllers.visit import VisitController as C
from ..services.export import roster_csv
from ..services.visit import suggest_counts
router=APIRouter()
@router.get('/visit-quotas')
def quotas(db=Depends(db_session),u=Depends(current_user)):return C.quotas(db)
@router.put('/visit-quotas')
def set_quotas(data:QuotaBatch,db=Depends(db_session),u=Depends(current_user)):
    if u.role!='admin':raise HTTPException(403,'仅负责人可以维护每日名额')
    return C.set_quotas(db,u,data)
@router.get('/visit-rosters')
def rosters(run_id:int|None=Query(default=None),db=Depends(db_session),u=Depends(current_user)):return C.rosters(db,run_id)
@router.get('/visit-rosters/{id}')
def roster(id:int,db=Depends(db_session),u=Depends(current_user)):return C.roster(db,id)
@router.post('/visit-rosters')
def create(data:SamplingInput,db=Depends(db_session),u=Depends(writer)):return C.create_roster(db,u,data)

@router.get('/visit-rosters/{id}/export')
def export(id:int,db=Depends(db_session),u=Depends(current_user)):return roster_csv(db,id)

@router.get('/visit-suggest')
def suggest(run_id:int,total:int=Query(default=6,ge=1,le=500),db=Depends(db_session),u=Depends(current_user)):return C.suggest(db,run_id,total)
