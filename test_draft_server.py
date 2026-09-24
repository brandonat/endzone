"""The draft board must not be able to change the season's rosters.

Like test_main.py, the endpoints are called directly as plain functions.
"""
import pytest
from fastapi import HTTPException

import draft_server


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "draft_state.json"
    path.write_text(draft_server.DRAFT_STATE_PATH.read_text())
    monkeypatch.setattr(draft_server, "DRAFT_STATE_PATH", path)
    return path


@pytest.mark.parametrize("call", [
    lambda: draft_server.rename_manager("m1", draft_server.ManagerRename(name="Someone")),
    lambda: draft_server.post_pick(draft_server.PickIn(team="KC", price=10, manager_id="m1")),
    lambda: draft_server.delete_pick("KC"),
], ids=["rename", "add_pick", "delete_pick"])
def test_write_endpoints_refuse_while_the_draft_is_locked(state_file, call):
    before = state_file.read_text()
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 423
    assert state_file.read_text() == before


def test_the_board_still_loads_while_locked(state_file):
    market = draft_server.get_teams()
    names = {m["name"] for m in market["managers"]}
    assert names == {"Bill", "Brandon", "Martin", "Klaus", "Greg", "Charlie", "Rahim"}
