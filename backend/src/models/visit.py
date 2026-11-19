from sqlalchemy import Column,Integer,String,Float,JSON,ForeignKey,UniqueConstraint
from ..config.database import Base
from ..config.settings import CONFIG
class VisitReservationLock(Base):
    __tablename__='visit_reservation_locks'
    id=Column(Integer,primary_key=True)
    purpose=Column(String(40),default='',unique=True,nullable=False)
class VisitDayQuota(Base):
    __tablename__='visit_day_quotas'
    day=Column(String(10),primary_key=True)
    capacity=Column(Integer,nullable=False)
class VisitRoster(Base):
    __tablename__='visit_rosters'
    id=Column(Integer,primary_key=True)
    run_id=Column(Integer,ForeignKey(CONFIG['run_table']+'.id'),nullable=False)
    name=Column(String(160),nullable=False)
    request_key=Column(String(120),unique=True,nullable=False)
    request_hash=Column(String(64),nullable=False)
    state=Column(String(20),default='reserved')
    summary=Column(JSON,nullable=False)
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)
class VisitRosterItem(Base):
    __tablename__='visit_roster_items'
    __table_args__=(UniqueConstraint('roster_id','reference',name='uq_roster_reference'),)
    id=Column(Integer,primary_key=True)
    roster_id=Column(Integer,ForeignKey('visit_rosters.id',ondelete='CASCADE'),nullable=False)
    reference=Column(String(120),nullable=False)
    cluster=Column(Integer,nullable=False)
    kind=Column(String(20),nullable=False)
    distance=Column(Float,nullable=False)
    day=Column(String(10),nullable=False,index=True)
