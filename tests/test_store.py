import asyncio

from app.models.schemas import Job
from app.store import SqliteJobStore


def test_sqlite_roundtrip(tmp_path):
    store = SqliteJobStore(tmp_path / "t.db")
    job = Job(id="abcd1234", filename="p.pdf", markdown="# hi")
    asyncio.run(store.create(job))

    got = asyncio.run(store.get("abcd1234"))
    assert got is not None and got.markdown == "# hi"

    got.step = "plan_complete"
    asyncio.run(store.save(got))
    again = asyncio.run(store.get("abcd1234"))
    assert again.step == "plan_complete" and again.updated_at >= again.created_at

    listing = asyncio.run(store.list())
    assert listing[0]["id"] == "abcd1234" and "markdown" not in listing[0]
    assert asyncio.run(store.get("nope0000")) is None
