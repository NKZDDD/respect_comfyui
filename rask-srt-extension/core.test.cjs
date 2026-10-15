const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {parseSrt, parseTime, matchCue} = require('./core.js');

test('Arabic, multiline and index zero remain intact', () => {
  const parsed = parseSrt('\uFEFF0\r\n00:00:00,120 --> 00:00:10,420\r\n[SPEAKER_02]: ل\r\nثان\r\n');
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.cues[0].number, '0');
  assert.equal(parsed.cues[0].text, 'ل\nثان');
  assert.equal(parsed.cues[0].speaker, 'SPEAKER_02');
  assert.equal(parseTime('00:00,120'), parsed.cues[0].start);
});
test('Invalid blocks are reported, never silently dropped', () => {
  assert.equal(parseSrt('1\n00:00:02,000 --> 00:00:01,000\n[SPEAKER_00]: a').errors.length, 1);
  assert.equal(parseSrt('16').errors.length, 1);
  assert.equal(parseSrt('0\n00:00:00,000 --> 00:00:01,000\na').errors.length, 1);
});
test('Match by time only across languages; duplicate timestamps remain ambiguous', () => {
  const cue = {start:120, end:10420, text:'ل', speaker:'SPEAKER_02'};
  assert.equal(matchCue(cue, [cue, {...cue, speaker:'SPEAKER_01'}]).status, 'ambiguous');
  assert.equal(matchCue({...cue,text:'这是译文，和页面完全不同'}, [cue]).status, 'matched');
  assert.equal(matchCue({...cue,start:0}, [cue]).status, 'unmatched');
  assert.equal(matchCue({...cue,text:'\u200fل '}, [cue]).status, 'matched');
  assert.equal(matchCue({...cue,end:11000}, [cue]).status, 'unmatched');
  assert.equal(matchCue({...cue,text:'different'}, [cue,{...cue,text:'different'}]).status, 'ambiguous');
});
test('Provided SRT has 31 valid cues, five speakers, and first desired SPEAKER_02', {skip: !process.env.RASK_SAMPLE_SRT}, () => {
  const path = process.env.RASK_SAMPLE_SRT;
  if (!path) return;
  const parsed = parseSrt(fs.readFileSync(path,'utf8'));
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.cues.length,31);
  assert.equal(new Set(parsed.cues.map(c => c.speaker)).size,5);
  assert.equal(parsed.cues[0].speaker,'SPEAKER_02');
});
