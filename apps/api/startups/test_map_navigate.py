"""The saved-map Apply path — the one that answered "evaluate failed" to every click.

`/startups/maps/{id}/navigate` reads `body.intent`, `body.query` and `body.history`. None of the
three was declared on `EvaluateIn`, so pydantic never carried them and the first attribute access
raised AttributeError — a 500, on every Apply on every saved map, from the moment the intent debugger
was added to that route. `/startups/evaluate` shares the model but never touches those fields, which
is why plain search kept working and only maps were broken.
"""
from api.startups.routes import EvaluateIn


def test_the_fields_the_map_path_reads_are_declared():
    b = EvaluateIn(contract={"text": "ai infra"})
    for f in ("intent", "query", "history"):
        assert hasattr(b, f), f"navigate_map reads body.{f}; without it every Apply is a 500"


def test_their_defaults_are_harmless():
    b = EvaluateIn(contract={"text": "x"})
    assert b.intent is False and b.query == "" and b.history == []


def test_navigate_reads_query_and_history_from_the_contract():
    """The shell builds ONE payload and posts it as `contract` — `query` and `history` ride inside
    it, not at the top level. Reading only the top level gave the intent debugger an empty query."""
    import inspect

    from api.startups import routes
    src = inspect.getsource(routes.build_router)
    i = src.index("navigate_map")
    seg = src[i:i + 3000]
    assert 'body.contract.get("query")' in seg
    assert 'body.contract.get("history")' in seg


def test_every_field_navigate_touches_exists_on_the_model():
    """A guard against the next one: whatever `navigate_map` reads off `body`, the model must have."""
    import inspect
    import re

    from api.startups import routes
    src = inspect.getsource(routes.build_router)
    i = src.index("async def navigate_map")
    seg = src[i:src.index("@r.post", i + 10)]
    touched = set(re.findall(r"\bbody\.([a-z_]+)", seg))
    fields = set(EvaluateIn.model_fields)
    assert touched <= fields, f"navigate_map reads {touched - fields} which EvaluateIn does not have"
