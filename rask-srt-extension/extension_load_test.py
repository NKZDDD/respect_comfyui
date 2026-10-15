"""Validate the actual MV3 package in an isolated offline Chromium profile."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parent
profile=root/'_test'/'extension-profile'
with sync_playwright() as p:
    context=p.chromium.launch_persistent_context(str(profile),headless=True,
        ignore_default_args=['--disable-extensions', '--headless'],
        args=['--headless=new',f'--disable-extensions-except={root}',f'--load-extension={root}'])
    try:
        worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker',timeout=20000)
        manifest=worker.evaluate('chrome.runtime.getManifest()')
        assert manifest['version']==json.loads((root/'manifest.json').read_text(encoding='utf-8'))['version']
        assert sorted(manifest['permissions'])==['activeTab','scripting']
        assert worker.evaluate('chrome.action.onClicked.hasListeners()')
        result={'manifestVersion':manifest['manifest_version'],'version':manifest['version'],
                'permissions':manifest['permissions'],'serviceWorkerRegistered':True,'actionHandlerRegistered':True}
        (root/'_test'/'extension-load.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    finally: context.close()
