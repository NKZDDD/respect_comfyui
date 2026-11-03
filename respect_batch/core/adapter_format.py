"""Provider bundle wire format shared with Studio. Validation NEVER executes Python."""
import ast
import hashlib
import json
import re

PROTOCOL = 1
MAX_BYTES = 2 * 1024 * 1024
IDENT = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


def encode(bundle):
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(bundle):
    return hashlib.sha256(encode(bundle)).hexdigest()


def validate(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {'protocol', 'version', 'modules', 'providers'}:
        raise ValueError('适配包必须包含 protocol、version、modules、providers')
    if type(bundle['protocol']) is not int or bundle['protocol'] != PROTOCOL:
        raise ValueError('适配包协议不兼容，请更新 Studio')
    if not isinstance(bundle['version'], str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', bundle['version']):
        raise ValueError('适配包版本格式不正确')
    modules, providers = bundle['modules'], bundle['providers']
    if not isinstance(modules, dict) or len(modules) > 100 or not isinstance(providers, list) or len(providers) > 100:
        raise ValueError('适配包最多包含 100 个模块和服务商')
    if len(encode(bundle)) > MAX_BYTES:
        raise ValueError('适配包最多 2 MB')
    for name, source in modules.items():
        if not IDENT.fullmatch(name) or name == 'base' or not isinstance(source, str):
            raise ValueError('非法模块名称或源码')
        try:
            tree = ast.parse(source, filename=name+'.py')
        except (SyntaxError, ValueError, RecursionError):
            raise ValueError('模块语法不正确：'+name) from None
        # Credentials belong in the Key library, not executable distribution files.
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r'\b(?:sk-|ic_live_)[A-Za-z0-9_-]{24,}', node.value):
                raise ValueError('源码疑似包含真实密钥，请移除后导出：'+name)
            if isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    target = (node.module or '').split('.')[0]
                    if target != 'base' and target not in modules:
                        raise ValueError('缺少依赖模块：'+target)
                if node.level == 0 and (node.module or '').startswith('core.providers.') and node.module != 'core.providers.base':
                    raise ValueError('服务商间依赖请使用相对导入：'+name)
    ids = set()
    for row in providers:
        if not isinstance(row, dict) or set(row) != {'id', 'name', 'module', 'class'}:
            raise ValueError('服务商声明字段不正确')
        if not isinstance(row['id'], str) or not IDENT.fullmatch(row['id']) or row['id'] in ids:
            raise ValueError('服务商 ID 无效或重复')
        if row['module'] not in modules or not isinstance(row['class'], str) or not row['class'].isidentifier():
            raise ValueError('服务商入口不存在')
        if not isinstance(row['name'], str) or not 1 <= len(row['name']) <= 160:
            raise ValueError('服务商名称不正确')
        ids.add(row['id'])
    return bundle


def select(bundle, ids):
    """Send only granted provider entries and their relative module dependencies."""
    providers = [p for p in bundle['providers'] if p['id'] in ids]
    needed = {p['module'] for p in providers}
    pending = list(needed)
    while pending:
        for node in ast.walk(ast.parse(bundle['modules'][pending.pop()])):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                target = (node.module or '').split('.')[0]
                if target != 'base' and target not in needed:
                    needed.add(target)
                    pending.append(target)
    return dict(protocol=PROTOCOL, version=bundle['version'], providers=providers,
                modules={k: v for k, v in bundle['modules'].items() if k in needed})
