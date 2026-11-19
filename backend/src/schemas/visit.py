from pydantic import BaseModel,Field,conint
class SamplingInput(BaseModel):
    run_id:int
    name:str=Field(min_length=2,max_length=160)
    request_key:str=Field(min_length=8,max_length=120)
    counts:dict[str,conint(strict=True,ge=0)]
    days:list[str]=Field(min_length=1,max_length=14)
    availability:dict[str,list[str]]=Field(default_factory=dict)
class QuotaInput(BaseModel):
    day:str
    capacity:conint(strict=True,ge=0,le=1000)
class QuotaBatch(BaseModel):
    quotas:list[QuotaInput]=Field(min_length=1,max_length=31)
