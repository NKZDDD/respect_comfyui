chrome.action.onClicked.addListener(async tab => {
  if (!tab.id) return;
  const url = new URL(tab.url || 'about:blank');
  if (url.origin !== 'https://app.rask.ai' || !url.pathname.includes('/project/')) {
    await chrome.action.setBadgeText({tabId: tab.id, text: 'Rask'});
    await chrome.action.setTitle({tabId: tab.id, title: '请先打开 app.rask.ai 的项目编辑页面，再点击插件'});
    return;
  }
  try {
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['core.js', 'engine.js', 'panel.js']});
    await chrome.action.setBadgeText({tabId: tab.id, text: ''});
  } catch (error) {
    await chrome.action.setBadgeText({tabId: tab.id, text: '!'});
    await chrome.action.setTitle({tabId: tab.id, title: `打开失败，请刷新网页后重试：${error.message}`});
  }
});
