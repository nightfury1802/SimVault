from datetime import datetime, timedelta

def _node(tier, days_ago, conf=None, valid_until=None, superseded_by=None):
    n = {"tier": tier, "created_at": (datetime.now()-timedelta(days=days_ago)).isoformat()}
    if conf is not None: n["confidence"] = conf
    if valid_until:      n["valid_until"] = valid_until
    if superseded_by:    n["superseded_by"] = superseded_by
    return n

def test_procedural_never_decays():
    from simvault.memory.scorer import effective_confidence
    assert effective_confidence(_node("procedural", 500)) == 1.0

def test_semantic_never_decays():
    from simvault.memory.scorer import effective_confidence
    assert effective_confidence(_node("semantic", 200)) == 1.0

def test_episodic_fresh():
    from simvault.memory.scorer import effective_confidence
    assert effective_confidence(_node("episodic", 5)) > 0.7

def test_episodic_stale():
    from simvault.memory.scorer import effective_confidence
    assert effective_confidence(_node("episodic", 91)) < 0.4

def test_working_past_decay():
    from simvault.memory.scorer import effective_confidence
    assert effective_confidence(_node("working", 8)) < 0.3

def test_expired_valid_until():
    from simvault.memory.scorer import effective_confidence
    past = (datetime.now()-timedelta(days=1)).isoformat()
    assert effective_confidence(_node("semantic", 0, valid_until=past)) == 0.0

def test_superseded():
    from simvault.memory.scorer import effective_confidence
    assert effective_confidence(_node("semantic", 0, superseded_by="newer")) == 0.0
