from pzaudit.inspectors import classify_ai_mention

def test_mouse_cursor_is_ignored():
    result = classify_ai_mention(
        "Small Dot Cursor",
        "Changes the mouse cursor and keeps the cursor visible."
    )
    assert result is None

def test_air_does_not_match_ai():
    result = classify_ai_mention(
        "Scrap Guns",
        "Craftable with Air Tanks after the recipe is unlocked."
    )
    assert result is None

def test_gameplay_ai():
    result = classify_ai_mention(
        "Restless Zombies",
        "Zombie AI pathfinding is active all the time."
    )
    assert result["classification"] == "gameplay_ai"

def test_ai_art_policy():
    result = classify_ai_mention(
        "Scrap Weapons",
        "IF YOU FORK THIS MOD DONT USE AI ARTWORK"
    )
    assert result["classification"] == "ai_policy_or_rejection"

def test_explicit_claude_code_use():
    result = classify_ai_mention(
        "Example",
        "I developed this mod using Claude to write and debug the Lua code."
    )
    assert result["classification"] == "explicit_genai_dev"
    assert "Claude" in result["tools"]

def test_cursor_ai_editor():
    result = classify_ai_mention(
        "Example",
        "I coded this mod with Cursor IDE and used it to write Lua scripts."
    )
    assert result["classification"] == "explicit_genai_dev"
    assert "Cursor" in result["tools"]

def test_generic_ai_dev():
    result = classify_ai_mention(
        "Example",
        "AI services were used during development and coding."
    )
    assert result["classification"] == "explicit_ai_dev_unspecified"
