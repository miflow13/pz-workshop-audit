from __future__ import annotations
import json, sqlite3
from pathlib import Path
SCHEMA="""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS mods (
 workshop_id TEXT PRIMARY KEY, creator_steam_id TEXT, title TEXT, description TEXT,
 time_created INTEGER, time_updated INTEGER, file_type INTEGER, file_size INTEGER,
 visibility INTEGER, subscriptions INTEGER, lifetime_subscriptions INTEGER,
 favorited INTEGER, lifetime_favorited INTEGER, tags_json TEXT NOT NULL DEFAULT '[]',
 raw_json TEXT NOT NULL, first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS crawl_state (
 name TEXT PRIMARY KEY,cursor TEXT NOT NULL,pages_committed INTEGER NOT NULL DEFAULT 0,
 steam_total INTEGER,complete INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
"""
def connect(path:Path):
    path.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(path); c.row_factory=sqlite3.Row; c.executescript(SCHEMA); return c
def get_state(c):
    c.execute("INSERT OR IGNORE INTO crawl_state(name,cursor) VALUES('workshop_census','*')"); c.commit()
    return c.execute("SELECT * FROM crawl_state WHERE name='workshop_census'").fetchone()
def upsert_mod(c,d):
    wid=str(d["publishedfileid"]); existed=c.execute("SELECT 1 FROM mods WHERE workshop_id=?",(wid,)).fetchone() is not None
    tags=[str(x.get("tag")) for x in (d.get("tags") or []) if isinstance(x,dict) and x.get("tag")]
    c.execute("""INSERT INTO mods(workshop_id,creator_steam_id,title,description,time_created,time_updated,file_type,file_size,
    visibility,subscriptions,lifetime_subscriptions,favorited,lifetime_favorited,tags_json,raw_json)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(workshop_id) DO UPDATE SET creator_steam_id=excluded.creator_steam_id,title=excluded.title,
    description=excluded.description,time_created=excluded.time_created,time_updated=excluded.time_updated,
    file_type=excluded.file_type,file_size=excluded.file_size,visibility=excluded.visibility,
    subscriptions=excluded.subscriptions,lifetime_subscriptions=excluded.lifetime_subscriptions,
    favorited=excluded.favorited,lifetime_favorited=excluded.lifetime_favorited,tags_json=excluded.tags_json,
    raw_json=excluded.raw_json,last_seen_at=CURRENT_TIMESTAMP""",
    (wid,str(d.get("creator","")) or None,d.get("title"),d.get("file_description"),d.get("time_created"),
     d.get("time_updated"),d.get("file_type"),d.get("file_size"),d.get("visibility"),d.get("subscriptions"),
     d.get("lifetime_subscriptions"),d.get("favorited"),d.get("lifetime_favorited"),
     json.dumps(tags),json.dumps(d,separators=(",",":"))))
    return not existed
def save_page(c,details,*,next_cursor,steam_total,complete):
    i=u=0
    for d in details:
        if upsert_mod(c,d): i+=1
        else: u+=1
    c.execute("""UPDATE crawl_state SET cursor=?,pages_committed=pages_committed+1,
    steam_total=COALESCE(?,steam_total),complete=?,updated_at=CURRENT_TIMESTAMP WHERE name='workshop_census'""",
    (next_cursor,steam_total,int(complete))); c.commit(); return i,u
def counts(c):
    s=get_state(c); n=c.execute("SELECT COUNT(*) FROM mods").fetchone()[0]
    return {"local_rows":n,"steam_total":s["steam_total"],"pages_committed":s["pages_committed"],"cursor":s["cursor"],"complete":bool(s["complete"])}
