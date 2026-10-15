"""Create a clean unpacked extension and ZIP without samples, profiles, or credentials."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

root=Path(__file__).resolve().parent
release=root.parent/'releases'
version=json.loads((root/'manifest.json').read_text(encoding='utf-8'))['version']
name='Rask-SRT-Speaker-Assistant-'+version
folder=release/name
folder.mkdir(parents=True,exist_ok=True)
files=['manifest.json','background.js','core.js','engine.js','panel.js','使用说明.md']
for file in files:
    shutil.copyfile(root/file,folder/file)
checks=json.loads((root/'_test'/'browser-results.json').read_text(encoding='utf-8'))
load=json.loads((root/'_test'/'extension-load.json').read_text(encoding='utf-8'))
assert len(checks['passed'])==9 and checks['version']==version and load['serviceWorkerRegistered'] and load['version']==version
report='''# 验证说明

- SRT 解析与保守匹配：4 项 Node 测试通过。
- 离线浏览器：9 项检查通过，覆盖提供的 HTML、31 条阿拉伯语 SRT、虚拟列表、延迟渲染、单条片段、缺失选项、停止、值回退和缺行。
- 已验证 31 条 SRT 的正文与网页完全不同时，仍能仅按起止时间完成扫描、点选、复核与导出，且网页正文保持不变。重复时间不会按正文猜选。
- Manifest V3 扩展实际加载通过，服务工作线程和工具栏按钮事件注册成功。

这是针对网页结构和离线模拟交互的验证，不是在线账号端到端验证。未在用户的 Rask 账号中验证服务端保存，也未点击生成按钮。请在实际项目中检查网页保存提示，刷新后重新扫描确认持久化。

实现：只使用当前页面 DOM 和真实下拉框事件；不访问 React 私有内部对象、不调用未公开的后端接口。网页结构或菜单协议改版后可能需要更新适配。
'''
(folder/'验证说明.md').write_text(report,encoding='utf-8')
files.append('验证说明.md')
archive=release/(name+'.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for file in files:
        z.write(folder/file,name+'/'+file)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert len(z.namelist())==len(files)
    assert json.loads(z.read(name+'/manifest.json'))['version']==version
manifest={'archive':str(archive),'size':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
          'files':{f:hashlib.sha256((folder/f).read_bytes()).hexdigest() for f in files},
          'tests':{'node':4,'browser':9,'translated_srt_31_cues':True,'extension_load':True}}
(release/(name+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'archive':str(archive),'size':manifest['size'],'sha256':manifest['sha256']},ensure_ascii=True))
