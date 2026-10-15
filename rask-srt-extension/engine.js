(function (root) {
  'use strict';
  const C = root.RaskSrtCore;
  const TEXT = '[data-testid="project-page-transcription-segment"]';
  const ROW = '[data-item-index]';
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const pageKey = () => location.origin + location.pathname;
  const identity = s => JSON.stringify([s.start, s.end]);
  const visible = el => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  function check(ctx) {
    if (ctx.cancelled) throw new Error('已停止。已经点选的片段请查看记录；再次扫描可核对当前状态。');
    if (ctx.page !== pageKey()) throw new Error('项目页面已切换，操作停止。请在当前项目重新扫描。');
  }
  function scroller() {
    const found = [...document.querySelectorAll('[data-virtuoso-scroller="true"]')]
      .filter(el => visible(el) && el.querySelector(TEXT));
    if (found.length !== 1) throw new Error('未找到唯一的 Rask 字幕列表。请等待字幕载入，并关闭搜索/筛选后重试。');
    return found[0];
  }
  function rows(list) { return [...list.querySelectorAll(ROW)].filter(el => el.querySelector(TEXT)); }
  function readRow(row) {
    const textEl = row.querySelector(TEXT);
    const edits = [...row.querySelectorAll('[contenteditable="true"]')];
    // In the supplied Rask DOM the first two editables are start/end times.
    const start = C.parseTime(edits[0]?.textContent || ''), end = C.parseTime(edits[1]?.textContent || '');
    const input = [...row.querySelectorAll('input')].find(el => /^SPEAKER_\d+$/.test(el.value));
    const combo = input?.parentElement.querySelector('[role="combobox"]');
    const index = Number(row.getAttribute('data-item-index'));
    if (!textEl || !combo || start === null || end === null || end <= start || !Number.isInteger(index)) {
      throw new Error(`第 ${index + 1} 个页面片段结构无法识别，已停止以避免改错行。`);
    }
    return {index, start, end, text: textEl.textContent, speaker: input.value, label: combo.textContent.trim()};
  }
  function findRow(list, expected) {
    return rows(list).find(row => {
      const s = readRow(row);
      return s.index === expected.index && identity(s) === identity(expected);
    });
  }
  async function waitFor(fn, ctx, timeout = 6000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      check(ctx);
      const result = fn();
      if (result) return result;
      await pause(100);
    }
    throw new Error('等待页面响应超时，未继续点选。请确认网页正常后重新扫描。');
  }
  async function settle(list, ctx) {
    let changed = Date.now();
    const started = changed;
    const observer = new MutationObserver(() => { changed = Date.now(); });
    observer.observe(list, {childList: true, subtree: true, characterData: true});
    try {
      await waitFor(() => {
        if (!list.isConnected) throw new Error('字幕列表已被替换，请重新扫描。');
        const box = list.getBoundingClientRect();
        const middle = box.top + Math.min(list.clientHeight / 2, Math.max(1, list.scrollHeight - list.scrollTop) / 2);
        const mounted = rows(list);
        const coversViewport = mounted.some(row => {
          const r = row.getBoundingClientRect();
          return r.top <= middle && r.bottom >= middle;
        });
        const shortList = list.scrollHeight <= list.clientHeight + 1 && mounted.length > 0;
        return (coversViewport || shortList) && Date.now() - started >= 500 && Date.now() - changed >= 200;
      }, ctx, 10000);
    } finally { observer.disconnect(); }
  }
  async function walk(ctx, visit) {
    const list = scroller(), originalTop = list.scrollTop;
    const seen = new Map();
    let bottomSignature = '', stableBottom = 0;
    const started = Date.now();
    try {
      list.scrollTop = 0;
      await settle(list, ctx);
      for (let step = 0; step < 6000 && Date.now() - started < 20 * 60 * 1000; step++) {
        check(ctx);
        const mounted = rows(list).map(readRow);
        for (const s of mounted) {
          check(ctx);
          const previous = seen.get(s.index);
          if (previous && identity(previous) !== identity(s)) throw new Error('扫描期间字幕时间或顺序发生变化，请重新扫描。');
          if (!previous) {
            seen.set(s.index, s);
            await visit(s, list);
          }
        }
        ctx.onProgress?.({seen: seen.size, scroll: Math.round(100 * list.scrollTop / Math.max(1, list.scrollHeight - list.clientHeight))});
        if (list.scrollTop + list.clientHeight >= list.scrollHeight - 3) {
          const signature = `${list.scrollHeight}/${[...seen.keys()].join(',')}`;
          stableBottom = signature === bottomSignature ? stableBottom + 1 : 0;
          bottomSignature = signature;
          if (stableBottom >= 3) {
            const ordered = [...seen.values()].sort((a,b) => a.index - b.index);
            if (!ordered.length || ordered.some((s,i) => s.index !== i)) {
              throw new Error('滚动后仍有页面片段未载入，扫描不完整；请清除筛选后重新扫描。');
            }
            return ordered;
          }
          await pause(600);
        } else {
          stableBottom = 0;
          list.scrollTop += Math.max(60, Math.floor(list.clientHeight * 0.6));
        }
        await settle(list, ctx);
      }
      throw new Error('扫描超时，未把未载入的片段计为成功。请重新扫描。');
    } finally {
      if (list.isConnected && ctx.page === pageKey()) list.scrollTop = originalTop;
    }
  }
  function buildPlan(segments, cues) {
    return cues.map(cue => {
      const timed = segments.filter(s => Math.abs(s.start-cue.start) <= 50 && Math.abs(s.end-cue.end) <= 50);
      if (timed.length === 0) return {cue, status:'missing', reason:'未找到对应时间的页面片段'};
      if (timed.length !== 1) return {cue, status:'blocked', reason:'多个页面片段时间相同，无法唯一匹配'};
      const segment = timed[0], match = C.matchCue(segment, cues);
      if (match.status !== 'matched') {
        return {cue, segment, status:'blocked', reason:'SRT 时间重复或匹配有歧义'};
      }
      return {cue, segment, status:segment.speaker === cue.speaker ? 'same' : 'ready', reason:''};
    });
  }
  async function scan(cues, ctx) {
    const segments = await walk(ctx, async () => {});
    return {page:ctx.page, createdAt:new Date().toISOString(), segments, items:buildPlan(segments,cues)};
  }
  function closeMenu(combo) {
    const id = combo?.getAttribute('aria-controls');
    const menu = id && document.getElementById(id);
    if (menu) menu.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',code:'Escape',bubbles:true}));
  }
  async function chooseSpeaker(list, item, ctx, record) {
    let row = findRow(list, item.segment);
    if (!row) throw new Error('片段已离开当前渲染区域，跳过');
    // React may replace the row after scrolling; never reuse an old DOM reference.
    row.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
    await settle(list, ctx);
    row = findRow(list, item.segment);
    if (!row) throw new Error('滚动后片段发生变化，跳过');
    let current = readRow(row);
    if (current.speaker === item.cue.speaker) { record.status='already'; return; }
    if (current.speaker !== item.segment.speaker) throw new Error('说话人在预览后已改变，请重新扫描');
    const input = [...row.querySelectorAll('input')].find(el => el.value === current.speaker);
    const combo = input.parentElement.querySelector('[role="combobox"]');
    if (combo.getAttribute('aria-disabled') === 'true') throw new Error('说话人下拉框当前不可用');
    if (document.querySelector('[role="listbox"]')) throw new Error('页面上另一个下拉框尚未关闭');
    try {
      check(ctx);
      combo.focus({preventScroll:true});
      combo.dispatchEvent(new MouseEvent('mousedown', {button:0, buttons:1, bubbles:true, cancelable:true, view:window}));
      combo.dispatchEvent(new MouseEvent('mouseup', {button:0, bubbles:true, view:window}));
      const menu = await waitFor(() => {
        const el = document.getElementById(combo.getAttribute('aria-controls'));
        return visible(el) && el.getAttribute('role') === 'listbox' ? el : null;
      }, ctx);
      const options = [...menu.querySelectorAll('[role="option"]')].filter(el => el.getAttribute('data-value') === item.cue.speaker);
      if (options.length !== 1 || !visible(options[0]) || options[0].getAttribute('aria-disabled') === 'true') {
        throw new Error(`下拉菜单中没有唯一可用的 ${item.cue.speaker}，未按显示序号猜选`);
      }
      check(ctx);
      row = findRow(list,item.segment);
      if (!row || readRow(row).speaker !== item.segment.speaker) throw new Error('点选前片段状态已变化');
      record.status='pending';
      record.clickedAt=new Date().toISOString();
      record.targetLabel=options[0].textContent.trim();
      options[0].click();
      await waitFor(() => {
        const fresh = findRow(list,item.segment);
        return fresh && readRow(fresh).speaker === item.cue.speaker;
      }, ctx);
      await pause(650);
      check(ctx);
      row = findRow(list,item.segment);
      if (!row || readRow(row).speaker !== item.cue.speaker) throw new Error('点选后页面未保持目标说话人');
      record.status='selected';
    } finally { closeMenu(combo); }
  }
  async function apply(plan, ctx, onRecord) {
    if (plan.page !== ctx.page) throw new Error('预览属于另一个项目，请重新扫描。');
    const pending = new Map(plan.items.filter(i => i.status === 'ready').map(i => [i.segment.index,i]));
    const records = [];
    // The caller receives records BEFORE any click, even if a stop or navigation interrupts it.
    await walk(ctx, async (segment, list) => {
      const item = pending.get(segment.index);
      if (!item) return;
      pending.delete(segment.index);
      const record = {number:item.cue.number, index:segment.index, start:item.cue.start, end:item.cue.end,
        before:item.segment.speaker, target:item.cue.speaker, status:'checking', reason:''};
      records.push(record); onRecord?.(record);
      try {
        if (identity(segment) !== identity(item.segment)) throw new Error('片段时间在预览后发生变化');
        await chooseSpeaker(list,item,ctx,record);
      } catch (error) {
        record.reason=error.message;
        record.status=record.clickedAt ? 'unverified' : 'skipped';
        check(ctx);
      } finally { onRecord?.(record); }
    });
    for (const item of pending.values()) {
      const record = {number:item.cue.number,index:item.segment.index,before:item.segment.speaker,target:item.cue.speaker,status:'skipped',reason:'执行时未再次找到片段'};
      records.push(record); onRecord?.(record);
    }
    ctx.onPhase?.('正在再次滚动核对已点选的说话人…');
    const verified = await walk(ctx, async () => {});
    for (const record of records.filter(r => r.clickedAt || r.status === 'already')) {
      const item = plan.items.find(i => i.segment?.index === record.index);
      const found = verified.filter(s => s.index === record.index && identity(s) === identity(item.segment));
      record.status = found.length === 1 && found[0].speaker === record.target ? 'verified' : 'unverified';
      if (record.status === 'unverified') record.reason='再次滚动核对未通过，请检查网页保存状态';
      onRecord?.(record);
    }
    return records;
  }
  root.RaskSrtEngine = {pageKey,readRow,buildPlan,scan,apply};
})(globalThis);
