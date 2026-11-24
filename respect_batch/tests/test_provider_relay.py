import base64
import io
from uuid import uuid4

import pytest
from core import model_catalog, provider_relay, providers
from core.providers.base import ImageTask
from PIL import Image


def test_native_upload_and_download_retry_use_one_relay_job(monkeypatch, tmp_path):
    """Exercise the normal provider entry point with an interrupted client download."""
    owner, key_id, revision, job = [str(uuid4()) for _ in range(4)]
    ticket = f"respect-relay-v1|{owner}|{key_id}|{revision}|api_key"
    image = io.BytesIO()
    Image.effect_noise((128, 128), 50).save(image, "PNG")
    data = image.getvalue()
    actions = []
    parts = []

    def transport(actual_owner, action, body):
        assert actual_owner == owner
        actions.append(action)
        if action == "catalog":
            return {"rows": [{"id": "fixture", "type": "image"}]}
        assert body["job"] == job
        if action == "open":
            assert body["provider"] == "julun" and body["key_id"] == key_id
            return {"state": "upload"}
        if action == "part":
            parts.append(base64.b64decode(body["data"]))
            return {"ok": True}
        if action == "submit":
            return {"state": "running"}
        if action == "status":
            return {"state": "ready"}
        assert action == "read"
        if actions.count("read") == 1:
            raise ConnectionError("interrupted")
        return {"data": base64.b64encode(data).decode(), "total": len(data)}

    monkeypatch.setattr(provider_relay.relay_transport, "call", transport)
    monkeypatch.setattr(provider_relay.relay_transport, "event_id", lambda: job)
    monkeypatch.setattr(provider_relay.submitted, "remember", lambda *args, **kw: None)
    assert model_catalog.fetch("julun", {"api_key": ticket})["models"] == ["fixture"]
    p = providers.build("julun", ticket, "https://relay.invalid")
    ref = tmp_path / "ref.png"
    ref.write_bytes(data)
    dest = str(tmp_path / "result.png")
    with pytest.raises(provider_relay.ApiError) as caught:
        p.generate_image(ImageTask("test", refs=[str(ref)], model="fixture"), dest)
    assert b"data:image/png;base64," in b"".join(parts)
    session, source = caught.value.download_retry
    session.save_item(source, dest)
    assert (tmp_path / "result.png").read_bytes() == data
    assert actions.count("submit") == 1

    def interrupted(_owner, action, _params):
        if action == "open":
            return {"state": "upload"}
        assert action == "part"
        raise ConnectionError("upload interrupted")

    dismissed = []
    monkeypatch.setattr(provider_relay.relay_transport, "call", interrupted)
    monkeypatch.setattr(provider_relay.submitted, "discard", lambda: dismissed.append(job))
    with pytest.raises(provider_relay.ApiError) as caught:
        p.generate_image(ImageTask("test", refs=[str(ref)], model="fixture"), dest)
    assert caught.value.err_code == "relay_not_submitted"
    assert dismissed == [job]
