from __future__ import annotations
import json,time,httpx
from dataclasses import dataclass
from .config import APP_ID,STEAM_QUERY_URL
@dataclass(frozen=True)
class QueryPage:
    details:list[dict]; next_cursor:str; total:int|None
class SteamWorkshopClient:
    def __init__(self,api_key,timeout=30.0,max_retries=5):
        self.api_key=api_key; self.max_retries=max_retries
        self.client=httpx.Client(timeout=timeout,headers={"User-Agent":"pzaudit/0.2","Accept":"application/json"})
    def __enter__(self): return self
    def __exit__(self,*args): self.client.close()
    def query_page(self,cursor,*,num_per_page=100):
        req={"query_type":1,"page":1,"cursor":cursor,"numperpage":num_per_page,"creator_appid":APP_ID,"appid":APP_ID,
             "return_tags":True,"return_vote_data":True,"return_metadata":True}
        params={"key":self.api_key,"input_json":json.dumps(req,separators=(",",":"))}
        last=None
        for attempt in range(self.max_retries):
            try:
                r=self.client.get(STEAM_QUERY_URL,params=params); r.raise_for_status(); body=r.json()["response"]
                ds=body.get("publishedfiledetails") or []; nc=str(body.get("next_cursor") or "")
                total=int(body["total"]) if body.get("total") is not None else None
                return QueryPage(ds,nc,total)
            except Exception as e:
                last=e
                if attempt==self.max_retries-1: break
                time.sleep(2**attempt)
        raise RuntimeError(f"Steam API request failed: {last}")
