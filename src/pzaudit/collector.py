from dataclasses import dataclass
from .db import get_state,save_page,upsert_mod
@dataclass
class CollectResult: pages:int=0; seen:int=0; inserted:int=0; updated:int=0
def collect(conn,client,*,limit=None,page_size=100):
    state=get_state(conn)
    if state["complete"]: return CollectResult()
    cursor=str(state["cursor"]); result=CollectResult()
    while True:
        page=client.query_page(cursor,num_per_page=page_size); details=page.details
        if limit is not None: details=details[:max(limit-result.seen,0)]
        if len(details)<len(page.details):
            for d in details:
                if upsert_mod(conn,d): result.inserted+=1
                else: result.updated+=1
            conn.commit(); result.seen+=len(details); return result
        complete=(not details) or (not page.next_cursor) or page.next_cursor==cursor
        i,u=save_page(conn,details,next_cursor=page.next_cursor or cursor,steam_total=page.total,complete=complete)
        result.pages+=1; result.seen+=len(details); result.inserted+=i; result.updated+=u
        print(f"page={result.pages} seen={result.seen} inserted={result.inserted} updated={result.updated} steam_total={page.total if page.total is not None else '?'}")
        if complete: return result
        cursor=page.next_cursor
        if limit is not None and result.seen>=limit: return result
