"""Load the same protocol-1 provider package as Studio, after online authorization.

Every content hash has its own Python namespace. Refresh switches the catalogue
atomically; running batches keep the classes and credentials they started with.
"""
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import types

from .adapter_format import MAX_BYTES, PROTOCOL, digest, encode, validate
from . import paths

_packages = {}
_classes = {}


class _Modules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        package, _, name = fullname.rpartition('.')
        if package in _packages and name in _packages[package]:
            return importlib.util.spec_from_loader(fullname, self)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        package, _, name = module.__name__.rpartition('.')
        module.__file__ = '<server-adapter:' + module.__name__ + '>'
        exec(compile(_packages[package][name], module.__file__, 'exec'), module.__dict__)


sys.meta_path.append(_Modules())


def load(bundle):
    from .providers.base import Provider
    validate(bundle)
    checksum = digest(bundle)
    if checksum in _classes:
        return _classes[checksum]
    name = 'core._adapters_' + checksum
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    pkg.__package__ = name
    sys.modules[name] = pkg
    sys.modules[name + '.base'] = sys.modules['core.providers.base']
    _packages[name] = bundle['modules']
    classes = {}
    try:
        for row in bundle['providers']:
            mod = importlib.import_module(name + '.' + row['module'])
            cls = getattr(mod, row['class'])
            if (not isinstance(cls, type) or not issubclass(cls, Provider)
                    or cls.id != row['id'] or cls.__module__ != mod.__name__):
                raise ValueError('适配包服务商入口声明不匹配')
            cap = cls().capabilities()
            if cap.get('id') != row['id'] or not cap.get('supports'):
                raise ValueError('适配包服务商能力声明不正确')
            classes[row['id']] = cls
    except Exception:
        _packages.pop(name, None)
        for key in list(sys.modules):
            if key == name or key.startswith(name + '.'):
                sys.modules.pop(key, None)
        raise
    _classes[checksum] = classes
    return classes


def classes_for(checksum):
    if checksum not in _classes:
        raise ValueError('任务使用的适配包未加载，请刷新后台配置')
    return _classes[checksum]


def install(uid, meta, fetch):
    """Return verified classes; never fall back to a bundled provider or offline grant."""
    if not isinstance(meta, dict) or meta.get('enabled') is not True:
        raise ValueError('后台尚未发布服务商适配包，请管理员导入并发布')
    checksum = meta.get('sha256', '')
    if (meta.get('protocol') != PROTOCOL or not isinstance(checksum, str)
            or len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum)):
        raise ValueError('适配包协议或校验码不正确，请更新批量客户端')
    if meta.get('missing'):
        raise ValueError('后台适配包缺少账号已分配的服务商，请管理员补充发布')
    cache = Path(paths.data_dir()) / 'adapter-cache' / (hashlib.sha256(uid.encode()).hexdigest() + '.json')
    bundle = None
    try:
        if cache.stat().st_size <= MAX_BYTES:
            candidate = json.loads(cache.read_bytes())
            if digest(candidate) == checksum:
                bundle = candidate
    except (OSError, ValueError, TypeError):
        pass
    if bundle is None:
        bundle = fetch(checksum).get('bundle')
    if digest(bundle) != checksum:
        raise ValueError('服务商适配包校验失败，请刷新后台配置重试')
    validate(bundle)
    if (bundle['version'] != meta.get('version') or
            sorted(p['id'] for p in bundle['providers']) != sorted(meta.get('providers', []))):
        raise ValueError('适配包与账号授权不一致，请刷新后台配置')
    try:
        classes = load(bundle)
    except Exception as exc:
        raise ValueError('适配包加载失败，请管理员回退适配包或更新客户端（' + type(exc).__name__ + '）') from None
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        temp = cache.with_suffix('.tmp')
        temp.write_bytes(encode(bundle))
        temp.replace(cache)
    except OSError:
        pass
    return classes
