# -*- coding: utf-8 -*-
"""不联网、不花钱的全套回归。

用一个假服务商（睡 N 秒然后写文件）验并发和闸门 —— 真服务商的协议在各自的
文件里已经消化过，这里要证的是**调度层**：并发真的并发了、配额真的卡住了、
失败真的分了类、跳过真的跳过了。
"""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import paths                                      # noqa: E402

FAKE_PROVIDER = '''# -*- coding: utf-8 -*-
import os, time
from core.apiutil import ApiError, RETRYABLE, BATCH_FATAL, TASK_FATAL
from core.providers.base import Provider

class FakerProvider(Provider):
    id = "faker"
    name = "假服务商"
    default_base_url = "http://localhost"
    supports = ("image", "video")

    def capabilities(self):
        return {"id": self.id, "name": self.name, "supports": list(self.supports),
                "default_base_url": self.default_base_url,
                "image": {"models": ["fast", "slow", "flaky", "broke", "nope"],
                          "default_model": "fast", "sizes": ["1024x1024"]},
                "video": {"models": ["fast"], "ratios": ["9:16"], "durations": [5]}}

    def list_models(self):
        return ["fast", "slow", "flaky", "broke", "nope"]

    def _fake(self, model, dest, log):
        time.sleep({"slow": 0.6}.get(model, 0.2))
        if model == "flaky":
            raise ApiError("网络抖了", status=503, kind=RETRYABLE)
        if model == "broke":
            raise ApiError("余额不足", status=402, kind=BATCH_FATAL)
        if model == "nope":
            raise ApiError("提示词违规", status=400, kind=TASK_FATAL)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as f:
            f.write(b"FAKE" * 200)
        return {"task_id": "t-" + os.path.basename(dest)}

    def generate_image(self, task, dest, *, log=print, cancel=None, **kw):
        return self._fake(task.model, dest, log)

    def generate_video(self, task, dest, *, log=print, cancel=None, **kw):
        return self._fake(task.model, dest, log)


class VideoOnlyProvider(Provider):
    id = "vidonly"
    name = "只做视频的假货"
    supports = ("video",)

    def capabilities(self):
        return {"id": self.id, "name": self.name, "supports": ["video"],
                "video": {"models": ["v"], "ratios": ["9:16"], "durations": [5]}}
'''


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """每个用例一个干净的数据目录 —— 绝不碰用户真实的 config.json。"""
    paths.set_data_dir(str(tmp_path / "data"))
    os.makedirs(paths.plugins_dir(), exist_ok=True)
    with open(os.path.join(paths.plugins_dir(), "faker.py"), "w",
              encoding="utf-8") as f:
        f.write(FAKE_PROVIDER)
    # 环境变量里的真密钥不该影响测试结果
    for k in list(os.environ):
        if k.endswith("_API_KEY"):
            monkeypatch.delenv(k, raising=False)
    from core import providers
    providers.reload_all()
    yield tmp_path
    paths.set_data_dir("")


def _cfg(**over):
    from core import config
    c = config.load()
    c.setdefault("providers", {})["faker"] = {"api_key": "x"}
    c["providers"]["vidonly"] = {"api_key": "x"}
    c["limits"] = {"global": 32, "per_provider": {}}
    c.update(over)
    config.save(c)
    return config.load()


def _wait(run, timeout=60):
    t0 = time.time()
    while run.status in ("排队中", "跑批中") and time.time() - t0 < timeout:
        time.sleep(0.05)
    return run


def _spec(tmp_path, n=8, **over):
    s = {"kind": "image", "provider": "faker", "model": "fast",
         "lines": "\n".join(f"第 {i} 条" for i in range(1, n + 1)),
         "concurrency": 4, "out_dir": str(tmp_path / "out"), "max_retry": 0}
    s.update(over)
    return s


# ---------------------------------------------------------------- 清单展开

def test_注释行和空行跳过():
    from core import batch
    rows = batch.parse_lines("一\n\n# 这条不跑\n二\n   \n三")
    assert [r["prompt"] for r in rows] == ["一", "二", "三"]


def test_竖线分三段_参考图用分号():
    from core import batch
    rows = batch.parse_lines(r"提示词 | C:\a.png;C:\b.png | 我的名字")
    assert rows[0]["prompt"] == "提示词"
    assert rows[0]["refs"] == [r"C:\a.png", r"C:\b.png"]
    assert rows[0]["name"] == "我的名字"


def test_文件名前面必须带序号_否则重名互相覆盖(tmp_path):
    """两条一模一样的提示词，成品必须是两个文件，不能覆盖成一个。"""
    from core import batch
    ts = batch.build_tasks(_spec(tmp_path, lines="一样的\n一样的"))
    assert len({t.dest for t in ts}) == 2


def test_每条出几张展开成几条独立任务(tmp_path):
    from core import batch
    ts = batch.build_tasks(_spec(tmp_path, n=3, repeat=4))
    assert len(ts) == 12
    assert len({t.dest for t in ts}) == 12


# ---------------------------------------------------------------- 配置

def test_打码串回存不会覆盖真密钥():
    from core import config
    cfg = config.load()
    cfg.setdefault("providers", {})["faker"] = {"api_key": "sk-REAL"}
    config.save(cfg)
    assert config.masked(config.load())["providers"]["faker"]["api_key"] == config.MASK
    back = config.apply_from_page(
        config.load(), {"providers": {"faker": {"api_key": config.MASK}},
                        "limits": {"global": 11}})
    assert back["providers"]["faker"]["api_key"] == "sk-REAL"
    assert back["limits"]["global"] == 11


def test_load_不会污染模块级DEFAULTS():
    """踩过的坑：浅拷贝让 load() 返回的内层 dict 就是 DEFAULTS 本身，
    往里写一把密钥等于改了默认值 —— 删掉它之后下次 load 又会回来。"""
    from core import config
    cfg = config.load()
    cfg["providers"]["偷偷塞进来"] = {"api_key": "x"}
    cfg["limits"]["per_provider"]["也是"] = 3
    assert config.DEFAULTS["providers"] == {}
    assert config.DEFAULTS["limits"]["per_provider"] == {}


def test_密钥删掉之后不会自己回来():
    from core import config
    cfg = config.load()
    cfg.setdefault("providers", {})["faker"] = {"api_key": "sk-REAL"}
    config.save(cfg)
    cfg2 = config.load()
    cfg2["providers"].pop("faker")
    config.save(cfg2)
    assert "faker" not in config.load()["providers"]


def test_没填密钥时回落环境变量(monkeypatch):
    from core import config
    monkeypatch.setenv("RESPECT_FAKER_API_KEY", "sk-FROM-ENV")
    assert config.provider_cfg(config.load(), "faker")["api_key"] == "sk-FROM-ENV"


# ---------------------------------------------------------------- 开跑前的拦截

def test_这家不做出图_要先于没填密钥报出来(tmp_path):
    """支持什么是类属性、不需要密钥就知道。排在密钥后面的话，选错家的人
    先被告知去填密钥，填完再撞一次才知道这家根本不做出图。"""
    from core import batch, config
    cfg = config.load()          # 故意不填任何密钥
    run = batch.start(_spec(tmp_path, provider="vidonly", kind="image"), cfg)
    assert "不做出图" in run.message
    assert "密钥" not in run.message


def test_没填密钥说清楚去哪填(tmp_path):
    from core import batch, config
    run = batch.start(_spec(tmp_path), config.load())
    assert "还没填密钥" in run.message and "RESPECT_FAKER_API_KEY" in run.message


def test_空清单不当成正常跑完(tmp_path):
    from core import batch
    run = batch.start(_spec(tmp_path, lines="# 全是注释\n\n"), _cfg())
    assert run.status == "已停止" and "空的" in run.message


# ---------------------------------------------------------------- 并发本身

def test_并发真的并发了(tmp_path):
    """12 条 x 每条 0.2 秒：串行要 2.4 秒，12 路并发应该 1 秒内。"""
    from core import batch
    cfg = _cfg()
    t0 = time.time()
    run = _wait(batch.start(_spec(tmp_path, n=12, concurrency=12), cfg))
    used = time.time() - t0
    assert run.counts()["完成"] == 12
    assert used < 1.2, f"12 路并发花了 {used:.1f}s，看着像在串行"


def test_每家配额卡得住批内并发(tmp_path):
    """批内填 12，但这家配额只有 2 —— 实际同时只能有 2 条在跑。"""
    from core import batch
    cfg = _cfg()
    cfg["limits"] = {"global": 32, "per_provider": {"faker": 2}}
    from core import config
    config.save(cfg)
    cfg = config.load()
    t0 = time.time()
    run = _wait(batch.start(_spec(tmp_path, n=8, concurrency=12), cfg))
    used = time.time() - t0
    assert run.counts()["完成"] == 8
    # 8 条 / 2 路 x 0.2 秒 ≈ 0.8 秒；要是配额没生效就是 0.2 秒
    assert used > 0.6, f"只用了 {used:.1f}s —— 配额闸没卡住"


def test_成品已存在就跳过_不重复花钱(tmp_path):
    from core import batch
    cfg = _cfg()
    _wait(batch.start(_spec(tmp_path, n=6), cfg))
    run = _wait(batch.start(_spec(tmp_path, n=6), cfg))
    assert run.counts()["跳过"] == 6 and run.counts()["完成"] == 0


def test_关掉跳过就会重跑(tmp_path):
    from core import batch
    cfg = _cfg()
    _wait(batch.start(_spec(tmp_path, n=4), cfg))
    run = _wait(batch.start(_spec(tmp_path, n=4, skip_existing=False), cfg))
    assert run.counts()["完成"] == 4 and run.counts()["跳过"] == 0


# ---------------------------------------------------------------- 失败怎么分类

def test_可重试的才重试_次数用满(tmp_path):
    from core import batch
    run = _wait(batch.start(
        _spec(tmp_path, n=2, model="flaky", max_retry=3), _cfg()))
    assert run.counts()["失败"] == 2
    assert all(t.attempts == 4 for t in run.tasks), [t.attempts for t in run.tasks]


def test_这一条本身的问题不重试(tmp_path):
    """提示词违规重试多少次都一样，还各扣一次钱。"""
    from core import batch
    run = _wait(batch.start(
        _spec(tmp_path, n=3, model="nope", max_retry=5), _cfg()))
    assert run.counts()["失败"] == 3
    assert all(t.attempts == 1 for t in run.tasks)


def test_整批致命就整批停_而且没发的不算失败(tmp_path):
    """余额不足时，剩下的一条都不该发出去；报数也要分开 ——
    报成「失败 20」会让人以为被扣了 20 次，然后去查账单。"""
    from core import batch
    run = _wait(batch.start(
        _spec(tmp_path, n=20, model="broke", concurrency=2, max_retry=3), _cfg()))
    c = run.counts()
    assert run.status == "已停止"
    # 终态一出现，统计就必须是**最终的**。原来 batch_fatal 当场把 status 改成
    # 「已停止」，而线程池还在收尾 —— 谁按 status 判断"跑完了"（命令行那个
    # 循环、任何轮询脚本）读到的就是半截统计，还据此定退出码。
    assert c["待跑"] == 0 and c["进行中"] == 0, f"终态时还有没结的任务：{c}"
    assert c["未发"] >= 15, c
    assert c["失败"] + c["未发"] == 20
    assert all(t.attempts <= 1 for t in run.tasks), "对整批致命做了无谓重试"
    没发的 = [t for t in run.tasks if t.status == "未发"]
    assert "没扣钱" in 没发的[0].error


def test_按次计费的家一次都不重投(tmp_path, monkeypatch):
    """小霸龙文档原文：创建 POST 只能提交一次，客户端不得自动重试。"""
    from core import batch
    monkeypatch.setattr(batch, "NO_RETRY", {"faker"})
    run = _wait(batch.start(
        _spec(tmp_path, n=2, model="flaky", max_retry=5), _cfg()))
    assert all(t.attempts == 1 for t in run.tasks)
    assert "不得自动重试" in run.tasks[0].error or "只发了一次" in run.tasks[0].error


# ---------------------------------------------------------------- 产物

def test_manifest_落盘且不含密钥(tmp_path):
    from core import batch
    from core.store import read_json
    run = _wait(batch.start(_spec(tmp_path, n=3, api_key="sk-DO-NOT-LEAK"), _cfg()))
    m = read_json(run.manifest_path, {})
    assert m["counts"]["完成"] == 3
    assert len(m["tasks"]) == 3
    assert "sk-DO-NOT-LEAK" not in str(m)


# ---------------------------------------------------------------- 参考图分派

def test_只收公网链接的家_没配对象存储要硬停(tmp_path):
    """给它 data URI 不会报错，参考图会被悄悄丢掉照样出图 ——
    图在、人不对，几百张里靠肉眼发现。所以宁可现在停。"""
    from core import providers, refs
    from core.apiutil import ApiError
    img = tmp_path / "ref.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 900)
    prov = providers.build("paisio", "k")
    resolve = refs.make_resolver(prov, "sd2-pro-720p", "video", {}, 0, "")
    with pytest.raises(ApiError) as e:
        resolve(str(img))
    assert "只收公网链接" in str(e.value)


def test_能吃图片内容的家_转成data_uri(tmp_path):
    from core import providers, refs
    img = tmp_path / "ref.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 900)
    prov = providers.build("lingganya", "k")
    out = refs.make_resolver(prov, "gpt-image-2", "image", {}, 0, "")(str(img))
    assert out.startswith("data:image/")


def test_空的参考图必须拦住(tmp_path):
    """0 字节的文件在每条分支上都过得去：传上去是个空对象、转 data URI 是段
    空数据 —— 服务商收到的是「有参考图」，实际什么都没有。"""
    from core import providers, refs
    from core.apiutil import ApiError
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    prov = providers.build("lingganya", "k")
    resolve = refs.make_resolver(prov, "gpt-image-2", "image", {}, 0, "")
    with pytest.raises(ApiError) as e:
        resolve(str(empty))
    assert "空文件" in str(e.value)


def test_参考图不存在时说清是哪个文件(tmp_path):
    from core import providers, refs
    from core.apiutil import ApiError
    prov = providers.build("lingganya", "k")
    resolve = refs.make_resolver(prov, "gpt-image-2", "image", {}, 0, "")
    with pytest.raises(ApiError) as e:
        resolve(str(tmp_path / "根本没有.png"))
    assert "根本没有.png" in str(e.value)


# ---------------------------------------------------------------- 服务商加载

def test_十七家内置全部加载得起来():
    from core import providers
    st = providers.status()
    builtin = [p for p in st["providers"] if p["builtin"]]
    assert len(builtin) == 17, [p["id"] for p in builtin]
    assert not st["errors"], st["errors"]


def test_打包后不会漏掉任何一家():
    """内置服务商是 importlib 动态加载的，打包成 exe 之后目录扫不到，
    只能按 _BUILTIN_ORDER 逐个 import —— 新加一家忘了写进去，
    它在 exe 里会缺席，而且**一句报错都没有**，下拉框里就是少一家。"""
    import glob
    from core.providers import _BUILTIN_ORDER
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "core", "providers")
    files = {os.path.splitext(os.path.basename(f))[0]
             for f in glob.glob(os.path.join(here, "*.py"))}
    files -= {"base"}
    files = {f for f in files if not f.startswith("_")}
    assert files == set(_BUILTIN_ORDER), \
        f"漏了 {files - set(_BUILTIN_ORDER)}；多了 {set(_BUILTIN_ORDER) - files}"


def test_每家的能力声明都渲染得出来():
    from core import providers
    for cap in providers.list_capabilities():
        assert not cap.get("broken"), f"{cap['id']}: {cap.get('broken')}"
        assert cap.get("name") and cap.get("supports")
        for kind in cap["supports"]:
            assert kind in cap, f"{cap['id']} 声明支持 {kind} 却没有这一节"
