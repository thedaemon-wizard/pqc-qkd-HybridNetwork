"""The export store accepts uploads from anyone who can reach the demo.

`/api/exports/save` writes a caller-supplied blob, under a caller-supplied
name, into a directory the same service then serves back over HTTP. That is
the one endpoint in this project where an anonymous visitor causes a file to
appear on the host, and it had no tests at all -- not for the path-traversal
guard, not for the size limit, not for the FIFO cap that stops a public demo
filling its own disk.

The guards were written; nothing checked that they still work. These tests
exercise the properties that make the endpoint safe to expose, so that
loosening one fails here rather than on the public host.
"""
from __future__ import annotations

import base64
import importlib

import pytest
from conftest import load_service_app
from fastapi.testclient import TestClient

load_service_app("webui-backend", "webui_backend_app")
main = importlib.import_module("webui_backend_app.main")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client whose export store is a temporary directory.

    EXPORT_DIR is read from the module global at call time, so patching the
    attribute is enough -- and it keeps the tests from touching the real
    /var/lib/pqcqkd-exports.
    """
    monkeypatch.setattr(main, "EXPORT_DIR", str(tmp_path))
    return TestClient(main.app)


def _save(client, name="chart", ext="png", payload=b"\x89PNG\r\n\x1a\n"):
    return client.post("/api/exports/save", json={
        "name": name, "ext": ext,
        "content_b64": base64.b64encode(payload).decode(),
    })


class TestSave:
    def test_round_trips_a_file(self, client):
        r = _save(client, payload=b"hello")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["size"] == 5

        got = client.get(body["url"])
        assert got.status_code == 200
        assert got.content == b"hello"

    def test_rejects_a_payload_over_the_limit(self, client, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_MAX_BYTES", 16)
        r = _save(client, payload=b"x" * 17)
        assert r.status_code == 413

    def test_rejects_content_that_is_not_base64(self, client):
        r = client.post("/api/exports/save", json={
            "name": "x", "ext": "png", "content_b64": "!!!not base64!!!",
        })
        assert r.status_code == 400

    def test_requires_content(self, client):
        r = client.post("/api/exports/save", json={"name": "x", "ext": "png"})
        assert r.status_code == 400

    @pytest.mark.parametrize("hostile", [
        "../../etc/passwd",
        "..",
        "/etc/shadow",
        "a/b/c",
        "x\\y",
        "\x00null",
    ])
    def test_a_hostile_name_cannot_escape_the_export_directory(
        self, client, tmp_path, hostile,
    ):
        r = _save(client, name=hostile)
        assert r.status_code == 200
        written = list(tmp_path.iterdir())
        assert len(written) == 1

        # The property is where the file LANDED, not whether its name contains
        # a suspicious substring. `../../etc/passwd` sanitises to the harmless
        # literal `..-..-etc-passwd`, which an earlier version of this test
        # rejected for containing "..", failing on correct behaviour. What
        # actually matters is that the resolved path is inside the store.
        assert written[0].resolve().parent == tmp_path.resolve()
        assert "/" not in written[0].name
        assert "\x00" not in written[0].name

    def test_a_hostile_extension_cannot_smuggle_a_path(self, client, tmp_path):
        r = _save(client, ext="../../sh")
        assert r.status_code == 200
        assert list(tmp_path.iterdir())[0].parent == tmp_path

    def test_names_are_bounded_in_length(self, client, tmp_path):
        _save(client, name="a" * 500)
        # Long enough to matter on filesystems with a 255-byte component limit.
        assert len(list(tmp_path.iterdir())[0].name) < 200


class TestCapacity:
    def test_keeps_only_the_most_recent_files(self, client, tmp_path, monkeypatch):
        """Without this cap a public demo fills its own disk.

        DEMO_MODE leaves this endpoint open on the reasoning that the store is
        capacity-bounded, so the bound is what makes that reasoning true.
        """
        monkeypatch.setattr(main, "EXPORT_MAX_FILES", 3)
        for i in range(8):
            assert _save(client, name=f"file{i}", payload=f"body{i}".encode()).status_code == 200
        assert len(list(tmp_path.iterdir())) == 3

    def test_listing_reports_what_survived(self, client, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_MAX_FILES", 2)
        for i in range(5):
            _save(client, name=f"f{i}")
        listed = client.get("/api/exports/list").json()["exports"]
        assert len(listed) == 2
        assert all("url" in e and "size" in e for e in listed)

    def test_listing_an_absent_store_is_empty_not_an_error(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(main, "EXPORT_DIR", str(tmp_path / "never-created"))
        r = client.get("/api/exports/list")
        assert r.status_code == 200
        assert r.json() == {"exports": []}


class TestDownloadAndDelete:
    @pytest.mark.parametrize("hostile", ["../main.py", "..%2Fmain.py", "a/b"])
    def test_download_refuses_to_leave_the_store(self, client, hostile):
        r = client.get(f"/api/exports/download/{hostile}")
        # 400 from the sanitiser, 404 from no such file, or 405 because the
        # client collapsed `../` before sending and the shortened path hit a
        # route that has no GET. The assertion is deliberately about the
        # outcome rather than the mechanism: what must never happen is a 200
        # carrying a file from outside the store.
        assert r.status_code in (400, 404, 405)
        assert r.status_code != 200

    def test_download_of_a_missing_file_is_404(self, client):
        assert client.get("/api/exports/download/20260101-000000-nope.png").status_code == 404

    def test_delete_removes_the_file(self, client, tmp_path):
        name = _save(client).json()["filename"]
        assert client.delete(f"/api/exports/{name}").status_code == 200
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("hostile", ["../main.py", "..%2Fmain.py"])
    def test_delete_refuses_to_leave_the_store(self, client, hostile):
        r = client.delete(f"/api/exports/{hostile}")
        assert r.status_code in (400, 404)

    def test_deleting_something_absent_is_not_an_error(self, client):
        # The picker deletes optimistically; a 500 here would surface as a
        # broken gallery for a file already gone.
        assert client.delete("/api/exports/20260101-000000-gone.png").status_code == 200


class TestTraversalGuardDirectly:
    """The filename guards, called as functions rather than over HTTP.

    Going through the client cannot reach them: httpx collapses `../` before
    sending, and a percent-encoded separator makes the path miss the route
    entirely, so every hostile URL 404s at the router. Deleting the guards
    outright left the HTTP tests green, which would have read as "traversal is
    covered" when nothing was exercising the check at all.

    They are still worth having and worth testing -- they are what holds if the
    route is ever changed to a `:path` parameter, or if a proxy in front
    normalises differently from Starlette.
    """

    @staticmethod
    def _call(coro):
        import asyncio
        return asyncio.run(coro)

    @pytest.mark.parametrize("hostile", ["../main.py", "../../etc/passwd", "a/../../b", ".."])
    def test_download_rejects_a_traversing_filename(self, client, hostile):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            self._call(main.export_download(hostile))
        assert e.value.status_code == 400

    @pytest.mark.parametrize("hostile", ["../main.py", "../../etc/passwd", ".."])
    def test_delete_rejects_a_traversing_filename(self, client, hostile):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            self._call(main.export_delete(hostile))
        assert e.value.status_code == 400

    def test_delete_does_not_remove_a_file_outside_the_store(self, client, tmp_path):
        from fastapi import HTTPException
        outside = tmp_path.parent / "must-survive.txt"
        outside.write_text("not yours")
        try:
            with pytest.raises(HTTPException):
                self._call(main.export_delete(f"../{outside.name}"))
            assert outside.exists()
        finally:
            outside.unlink(missing_ok=True)
