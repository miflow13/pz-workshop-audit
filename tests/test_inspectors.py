import json
from pathlib import Path
from pzaudit.db import connect
from pzaudit.inspectors import overview, timeline, top_tags, classify_ai_mention

def insert_mod(conn,wid,creator,title,desc,created,tags):
    conn.execute("""INSERT INTO mods(workshop_id,creator_steam_id,title,description,time_created,tags_json,raw_json)
                    VALUES(?,?,?,?,?,?, '{}')""",(wid,creator,title,desc,created,json.dumps(tags)))
    conn.commit()

def test_overview_timeline_tags(tmp_path: Path):
    c=connect(tmp_path/"t.db")
    insert_mod(c,"1","a","One","desc",1609459200,["Mod","QoL"])
    insert_mod(c,"2","b","Two","desc",1640995200,["Mod"])
    assert overview(c)["items"]==2
    assert timeline(c)==[("2021",1),("2022",1)]
    assert top_tags(c,1)==[("Mod",2)]

def test_explicit_disclosure():
    r=classify_ai_mention("Example","I made this mod using Claude to help write the Lua scripts.")
    assert r["classification"]=="explicit_disclosure"
    assert "Claude" in r["tools"]

def test_generic_ai_is_ambiguous():
    r=classify_ai_mention("Smarter Zombies","Improves AI pathfinding and survivor behavior.")
    assert r["classification"]=="ambiguous_ai"
