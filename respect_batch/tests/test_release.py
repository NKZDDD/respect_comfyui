"""发行版的路由、凭据边界和加密封装；全部使用专门的假凭据。"""
import copy
import http.client
import json
import os
from pathlib import Path
import threading
import time

import pytest

from tests.test_batch import sandbox  # noqa: F401
from core import batch, config, distribution, paths, providers, release
from tools.build_release import make_profile, seal_module, render_page


@pytest.fixture
def locked(monkeypatch):
    profile = make_profile({"config": {
        "providers": {"ake": {"api_key": "TEST-AKE-SECRET-ONLY"},
                      "aicopy": {"api_key": "TEST-AICOPY-SECRET-ONLY"}},
        "upload": {"endpoint": "https://store.invalid", "public_base_url": "https://cdn.invalid",
                   "bucket": "test", "access_key": "TEST-STORAGE-ID", "secret_key": "TEST-STORAGE-SECRET"}
    }})
    monkeypatch.setattr(distribution, "ENABLED", True)
    monkeypatch.setattr(distribution, "profile", lambda: copy.deepcopy(profile))
    monkeypatch.setattr(distribution, "page", lambda: render_page(
        (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")))
    return profile


def request_spec(profile):
    row = next(m for m in profile["models"] if m["provider"] == "aicopy" and m["model"] == "sd2.0-720满血-不卡脸（按秒）")
    return {"provider": "preset", "kind": "video", "model": row["id"],
            "tasks": [{"prompt": "测试生成", "refs": []}], "duration": 5}


def test_release_ignores_local_credentials_and_environment(locked, tmp_path, monkeypatch):
    Path(paths.config_path()).write_text(json.dumps({"providers": {"aicopy": {"api_key": "ATTACKER"}}}))
    monkeypatch.setenv("AICOPY_API_KEY", "ATTACKER")
    cfg = config.load()
    assert config.provider_cfg(cfg, "aicopy")["api_key"] == "TEST-AICOPY-SECRET-ONLY"
    assert config.provider_cfg({}, "aicopy") == {}
    with pytest.raises(ValueError, match="不能"):
        config.save(cfg)


@pytest.mark.parametrize("field,value", [("provider", "ake"), ("base_url", "https://other.invalid"),
                                        ("api_key", "OTHER"), ("proxy", "http://other.invalid"),
                                        ("extra", {"url": "https://other.invalid"}), ("model", "sd2.0-720满血-不卡脸（按秒）")])
def test_release_rejects_routing_overrides_before_build(locked, monkeypatch, field, value):
    raw = request_spec(locked)
    raw[field] = value
    monkeypatch.setattr(providers, "build", lambda *a, **k: pytest.fail("必须在创建服务商前拒绝"))
    with pytest.raises(ValueError):
        batch.start(raw, {})


def test_release_uses_selected_key_and_runs_batch(locked, tmp_path, monkeypatch):
    seen = []
    class Fake:
        name = "测试模型"
        def capabilities(self):
            return {"video": {}}
        def needs_url(self, *a):
            return False
        def needs_bytes(self, *a):
            return False
        def accepts_url(self, *a):
            return False
        def generate_video(self, task, dest, **kw):
            seen.append(task.model)
            kw["log"]("小裴 api.aicopy.top 阿珂 snumom.com https://cdn.invalid/result.mp4")
            Path(dest).write_bytes(b"test" * 200)
            return {"task_id": "fake", "echo": "TEST-AICOPY-SECRET-ONLY", "provider": "aicopy",
                    "source": "https://api.aione.help/image.png", "raw": {"message": "阿珂"}}
    def build(pid, key, base, proxy, timeout):
        assert pid == "aicopy" and key == "TEST-AICOPY-SECRET-ONLY"
        assert base == "https://api.aicopy.top" and proxy == "direct"
        return Fake()
    monkeypatch.setattr(providers, "build", build)
    raw = request_spec(locked)
    raw.update(out_dir=str(tmp_path / "out"), repeat=3)
    run = batch.start(raw, {"providers": {"aicopy": {"api_key": "UNTRUSTED"}}})
    end = time.monotonic() + 5
    while run.status in ("排队中", "跑批中") and time.monotonic() < end:
        time.sleep(.02)
    assert run.counts()["完成"] == 3
    assert seen == ["sd2.0-720满血-不卡脸（按秒）"] * 3
    run.write_manifest()
    manifest = Path(run.manifest_path).read_text(encoding="utf-8")
    logs = Path(run.log_path).read_text(encoding="utf-8")
    public = json.dumps(release.redact(run.snapshot()), ensure_ascii=False)
    for output in (manifest, logs, public):
        assert all(term not in output for term in ("TEST-AICOPY-SECRET-ONLY", "阿珂", "小裴",
                   "aicopy", "snumom", "aione", "https://cdn.invalid"))
    assert json.loads(manifest)["tasks"][0]["provider"] == "Respect"


def test_release_cannot_load_external_python(locked, tmp_path):
    marker = tmp_path / "executed"
    Path(paths.plugins_dir(), "inject.py").write_text(f"open({str(marker)!r}, 'w').write('bad')")
    providers.reload_all()
    assert set(providers.REGISTRY) == {"ake", "aicopy"}
    assert not marker.exists()


def test_release_references_must_come_from_uploads(locked, tmp_path):
    image = tmp_path / "outside.png"
    image.write_bytes(b"image")
    raw = request_spec(locked)
    for refs in [[str(image)], ["https://other.invalid/image.png"], ["data:image/png;base64,xxx"]]:
        raw["refs"] = refs
        with pytest.raises(ValueError, match="导入"):
            release.prepare(raw)


def test_release_respects_zero_reference_limit(locked):
    raw = request_spec(locked)
    item = next(m for m in locked["models"] if m["provider"] == "aicopy")
    item["options"]["max_refs"] = 0
    from core.assets import save
    path = save(b"fake image", "image.png")["path"]
    raw.update(model=item["id"], kind="video", duration=0, ref_slots=[[path]])
    with pytest.raises(ValueError, match="最多 0 张"):
        release.prepare(raw)


def test_sealed_profile_hides_plaintext_and_authenticates(locked):
    html = distribution.page()
    source = seal_module(locked, html)
    assert "TEST-AICOPY-SECRET-ONLY" not in source and "TEST-STORAGE-SECRET" not in source
    scope = {}
    exec(source, scope)
    assert scope["ENABLED"] and scope["profile"]() == locked
    assert scope["page"]() == html
    assert "<html" not in source and "阿珂" not in source and "小裴" not in source
    # 改动关联数据后必须解密失败，不可回退到用户配置或开发模式。
    bad = source.replace("Respect-Batch-Release-v1", "Respect-Batch-Release-v2")
    exec(bad, scope)
    from cryptography.exceptions import InvalidTag
    with pytest.raises(InvalidTag):
        scope["profile"]()


def test_release_http_only_exposes_user_operations(locked, monkeypatch):
    from core import server
    monkeypatch.setitem(server._RUN, "cur", None)
    httpd = server.serve(port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    def call(route, data=None, session=True, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=3)
        headers = {"Content-Type": "application/json"}
        if session:
            headers["X-Respect-Session"] = server._SESSION
        if origin:
            headers["Origin"] = origin
        conn.request("POST" if data is not None else "GET", route,
                     json.dumps(data) if data is not None else None, headers)
        response = conn.getresponse()
        result = response.status, response.read().decode()
        conn.close()
        return result
    try:
        status, home = call('/')
        assert status == 200 and 'Respect 创作服务' in home
        assert '__RELEASE_SESSION__' not in home
        assert 'id="tab-set"' not in home and 'api/config' not in home
        status, text = call('/api/boot')
        assert status == 200
        assert "SECRET" not in text and "api.aicopy.top" not in text
        assert json.loads(text)["distribution"]
        for route in ('/api/config', '/api/import_studio', '/api/rescan', '/api/models', '/api/selftest', '/api/accounts'):
            assert call(route, {})[0] == 403
        assert call('/api/start', request_spec(locked), session=False)[0] == 403
        assert call('/api/boot', origin='https://other.invalid')[0] == 403
        assert call('/api/open', {"path": os.__file__})[0] == 403
        assert call('/api/start', {"spec": {**request_spec(locked), "base_url": "https://other.invalid"}})[0] == 400
    finally:
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()


def test_formal_build_requires_complete_private_configuration():
    source = {"config": {"providers": {"ake": {}, "aicopy": {}}}}
    with pytest.raises(ValueError, match="Key"):
        make_profile(source)
    preview = make_profile(source, preview=True)
    assert preview["preview"]
    assert {r["provider"] for r in preview["models"]} == {"ake", "aicopy"}


def test_server_refuses_port_already_in_use():
    from core import server
    first = server.serve(port=0)
    try:
        with pytest.raises(OSError):
            second = server.serve(port=first.server_port)
            second.server_close()
    finally:
        first.server_close()


def test_preview_strips_supplied_credentials_and_never_runs(locked):
    preview = make_profile(locked, preview=True)
    assert all(not p["api_key"] for p in preview["config"]["providers"].values())
    assert "SECRET" not in json.dumps(preview)
    locked["preview"] = True
    with pytest.raises(ValueError, match="预览版"):
        release.prepare(request_spec(locked))


def test_exactly_three_models_and_separate_upload_backends(locked):
    from core import refs, uploader
    assert {(r["provider"], r["model"]) for r in locked["models"]} == {
        ("ake", "minimax_h3-768p"), ("ake", "grok-imagine-video-1.5（按次）"),
        ("aicopy", "sd2.0-720满血-不卡脸（按秒）")}
    cfg = config.load()
    assert refs.upload_config(cfg, "ake")["secret_key"] == "TEST-STORAGE-SECRET"
    small = refs.upload_config(cfg, "aicopy")
    assert small["backend"] == "aicopy" and small["api_key"] == "TEST-AICOPY-SECRET-ONLY"
    assert "secret_key" not in small
    assert all(uploader.configured(refs.upload_config(cfg, pid)) for pid in ("ake", "aicopy"))


@pytest.mark.parametrize("model,resolution", [("minimax_h3-768p", "768P"),
                                            ("grok-imagine-video-1.5（按次）", "720P")])
def test_ake_uses_exact_model_and_reference_contract(model, resolution, monkeypatch, tmp_path):
    from core.providers.ake import AkeProvider
    from core.providers.base import VideoTask
    provider = AkeProvider("FAKE")
    sent = []
    def request(method, route, **kwargs):
        assert method == "POST" and route == "/v1/videos"
        sent.append(kwargs["json_body"])
        return {"url": "https://cdn.invalid/out.mp4"}
    monkeypatch.setattr(provider.session, "request", request)
    monkeypatch.setattr(provider.session, "save_item", lambda url, path: None)
    provider.generate_video(VideoTask("测试", refs=["https://r2.invalid/ref.png"],
        duration=5, model=model, resolution=resolution), str(tmp_path/'out.mp4'), log=lambda *a:None)
    assert sent[0]["model"] == model and sent[0]["seconds"] == "5"
    assert sent[0]["size"] == resolution
    assert sent[0]["reference_images"] == [{"url": "https://r2.invalid/ref.png"}]


def test_aicopy_exact_sd_model_and_reference_contract():
    from core.providers.aicopy import AicopyProvider
    from core.providers.base import VideoTask
    model = "sd2.0-720满血-不卡脸（按秒）"
    route, body, poll = AicopyProvider().build_video_body(VideoTask("测试", refs=["https://image.invalid/ref.png"], duration=5, model=model))
    assert route == "/v1/videos" and poll == "/v1/videos/{id}"
    assert body["model"] == model and body["seconds"] == 5
    assert body["input_reference"] == {"url": "https://image.invalid/ref.png"}


def test_aicopy_uploader_uses_only_its_key_and_blocks_redirect(monkeypatch, tmp_path):
    from core import uploader
    from core.apiutil import ApiError
    path = tmp_path / "ref.png"
    path.write_bytes(b"fake image")
    monkeypatch.setattr(uploader, "encode_ref", lambda *a, **k: (b"upload test image", "image/png", ".png", "unchanged"))
    class Session:
        trust_env = True
        def post(self, url, **kwargs):
            assert not self.trust_env
            assert url == "https://api.aione.help/v1/uploads"
            assert kwargs["headers"]["Authorization"] == "Bearer FAKE-AICOPY-UPLOAD"
            assert kwargs["allow_redirects"] is False and "image" in kwargs["files"]
            class Response:
                status_code=302
                text=""
            return Response()
        def close(self):
            pass
    import requests
    monkeypatch.setattr(requests, "Session", Session)
    with pytest.raises(ApiError, match="302"):
        uploader.to_url(str(path), {"backend":"aicopy", "api_key":"FAKE-AICOPY-UPLOAD"})


def test_release_page_contains_only_user_functions(locked):
    page = distribution.page().decode()
    assert 'id="model"' in page and 'id="folderSection"' in page
    assert '<input type="hidden" id="prov" value="preset">' in page
    assert all(term not in page for term in ('data-admin>', 'id="tab-set"', 'id="up_secret_key"',
               'api/config', 'api/import_studio', 'api/models', 'applyTemplate', '庄园', '阿珂', '小裴'))


def test_release_upload_cache_keeps_urls_in_memory_only(locked, monkeypatch, tmp_path):
    from core import uploader
    monkeypatch.setattr(uploader, '_MEM', {})
    monkeypatch.setattr(uploader, 'read_json', lambda *a: pytest.fail('不能读取旧的明文上传缓存'))
    monkeypatch.setattr(uploader, 'write_json', lambda *a: pytest.fail('不能保存上传服务地址'))
    assert uploader._cache_get(str(tmp_path), 'missing') == ''
    uploader._cache_put(str(tmp_path), 'ref', 'https://cdn.invalid/ref.png')
    assert uploader._cache_get(str(tmp_path), 'ref') == 'https://cdn.invalid/ref.png'


def test_release_errors_and_records_hide_upstream_details(locked):
    value = {'provider': 'ake', 'model': 'minimax_h3-768p',
             'message': "小裴请求失败，host='api.aione.help'；阿珂 https://snumom.com/v1/videos",
             'meta': {'source': 'https://cdn.invalid/file.mp4', 'raw': 'private'},
             'gate': {'global_limit': 4, 'per_provider_limit': {'ake': 4}}}
    result = release.redact(value)
    assert result['provider'] == 'Respect' and result['model'] == 'H3 768p'
    assert result['gate'] == {'global_limit': 4} and 'meta' not in result
    assert all(term not in json.dumps(result, ensure_ascii=False)
               for term in ('阿珂', '小裴', 'snumom', 'aione', '"ake"', 'https://'))


def test_brand_redaction_preserves_user_text_and_file_paths(locked):
    path = r'C:\images\庄园里的小裴.png'
    content = {'path': path, 'dest': path, 'refs': [path], 'name': '阿珂.png',
               'out_dir': r'C:\用户项目\庄园', 'prompt': '庄园里的人物走向镜头'}
    assert release.redact(content) == content


