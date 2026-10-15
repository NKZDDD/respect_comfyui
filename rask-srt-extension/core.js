/* Shared parsing and conservative matching; no page mutations. */
(function (root) {
  'use strict';
  function parseTime(value) {
    const match = String(value).trim().match(/^(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})$/);
    if (!match) return null;
    const hours = Number(match[1] || 0), minutes = Number(match[2]), seconds = Number(match[3]);
    if (minutes > 59 || seconds > 59) return null;
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + Number(match[4].padEnd(3, '0'));
  }
  function parseSrt(text) {
    const blocks = String(text).replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').trim().split(/\n\s*\n/);
    const cues = [], errors = [];
    blocks.forEach((block, index) => {
      const lines = block.split('\n');
      const number = /^\d+$/.test(lines[0].trim()) ? lines.shift().trim() : String(index + 1);
      const times = (lines.shift() || '').match(/^\s*(\S+)\s*-->\s*(\S+)\s*$/);
      const start = times ? parseTime(times[1]) : null, end = times ? parseTime(times[2]) : null;
      const body = lines.join('\n').trim();
      const tag = body.match(/^\[\s*(SPEAKER_\d+)\s*\]\s*[:\uff1a]?\s*([\s\S]*)$/i);
      if (start === null || end === null || end <= start || !tag || !tag[2].trim()) {
        errors.push({ block: index + 1, number, reason: '时间、说话人标记或正文无效' });
        return;
      }
      cues.push({ number, start, end, speaker: tag[1].toUpperCase(), text: tag[2].trim() });
    });
    return { cues, errors };
  }
  function matchCue(segment, cues, tolerance = 50) {
    if (!Number.isFinite(segment.start) || !Number.isFinite(segment.end)) return { status: 'invalid-time' };
    const candidates = cues.filter(c => Math.abs(c.start - segment.start) <= tolerance && Math.abs(c.end - segment.end) <= tolerance);
    if (!candidates.length) return { status: 'unmatched' };
    // Text is deliberately ignored, including when timestamps are ambiguous.
    if (candidates.length !== 1) return { status: 'ambiguous' };
    const cue = candidates[0];
    return { status: 'matched', cue };
  }
  const api = { parseTime, parseSrt, matchCue };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.RaskSrtCore = api;
})(globalThis);
