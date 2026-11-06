import test from 'node:test';
import assert from 'node:assert/strict';
import { createPromptContext, createPromptDeliveryLedger, referencePart, textPart, validatePromptContext, formatPromptContextText, formatPromptMessage, formatPromptReference, promptReferenceIds, resolveAttachmentPaths } from './index.js';

const reference = { resource: { kind: 'workspace-file', path: '/work/STEP/my part.step', revision: 'v1' }, target: { kind: 'cad-selector', selectors: ['o1.2.f45'] } };
test('one context retains image/reference relationships and formats canonical references', () => {
  const capture = Promise.resolve(new Blob(['png'], { type: 'image/png' }));
  const context = createPromptContext([referencePart(reference, 'face'), { id: 'image', kind: 'attachment', name: 'view.png', mimeType: 'image/png', content: capture, about: ['face'] }, textPart('Increase the clearance.')]);
  assert.equal(validatePromptContext(context), context);
  assert.equal(context.parts[1].content, capture);
  assert.equal(formatPromptContextText(context), '"/work/STEP/my part.step"#o1.2.f45\nIncrease the clearance.');
  assert.notEqual(createPromptContext([textPart('next')]).operationId, context.operationId);
});
test('a message says what the person wrote, then the file, its references and a picture saved as a file', () => {
  const file = { resource: reference.resource, target: { kind: 'whole-resource' } };
  const annotation = { id: 'annotation', kind: 'attachment', name: 'part-annotation.png', mimeType: 'image/png', content: new Blob(), about: ['file'], label: 'Annotation' };
  const context = createPromptContext([textPart('Round this edge.\n'), referencePart(file, 'file'), referencePart(reference, 'face'), annotation]);
  assert.equal(formatPromptMessage(context, { attachmentPath: part => `/tmp/${part.name}` }),
    'Round this edge.\n\nFile: "/work/STEP/my part.step"\nReferences:\n"/work/STEP/my part.step"#o1.2.f45\nAnnotation: /tmp/part-annotation.png');
  // A picture sent beside the text is not named in it.
  assert.equal(formatPromptMessage(createPromptContext([textPart('Why?'), referencePart(file, 'file'), annotation])), 'Why?\n\nFile: "/work/STEP/my part.step"');
});

test('a file already saved says where, as soon as it is; one that never will be fails the context', async () => {
  const file = { resource: reference.resource, target: { kind: 'whole-resource' } };
  const views = { id: 'views', kind: 'attachment', name: 'part.job.json', mimeType: 'application/json', content: new Blob(), about: ['file'],
    label: 'Views', path: Promise.resolve('/tmp/p/part-1.job.json') };
  const context = createPromptContext([textPart('Thicker.'), referencePart(file, 'file'), views]);
  const paths = await resolveAttachmentPaths(context);
  assert.deepEqual([...paths], [['views', '/tmp/p/part-1.job.json']]);
  assert.equal(formatPromptMessage(context, { attachmentPath: part => paths.get(part.id) }),
    'Thicker.\n\nFile: "/work/STEP/my part.step"\nViews: /tmp/p/part-1.job.json');
  assert.throws(() => validatePromptContext({ ...context, parts: [...context.parts.slice(0, 2), { ...views, path: 7 }] }), /attachment path/);
});
test('code targets preserve explicit ranges rather than borrowing the CAD fragment grammar', () => {
  const code = { resource: { kind: 'workspace-file', path: '/work/src/bracket.py' }, target: { kind: 'text-range', start: { line: 4, character: 2 }, end: { line: 6, character: 0 } } };
  assert.equal(formatPromptReference(code), '/work/src/bracket.py:5:3-7:1');
});
test('a reference names its ids as a person reads them: each selector, a range from 1, or its label', () => {
  assert.deepEqual(promptReferenceIds({ ...reference, target: { kind: 'cad-selector', selectors: ['o1.f2', 'o1.e3'] } }), ['o1.f2', 'o1.e3']);
  const range = { resource: { kind: 'workspace-file', path: '/work/a.py' }, target: { kind: 'text-range', start: { line: 0, character: 4 }, end: { line: 2, character: 0 } } };
  assert.deepEqual(promptReferenceIds(range), ['1:5–3:1']);
  assert.deepEqual(promptReferenceIds({ ...range, label: 'def plate' }), ['def plate']);
  assert.deepEqual(promptReferenceIds({ ...range, target: { kind: 'whole-resource' } }), []);
});

test('invalid bundles fail before delivery, including dangling relationships and unknown targets', () => {
  assert.throws(() => createPromptContext([textPart('a'), textPart('b')]), /unique/);
  assert.throws(() => createPromptContext([{ id: 'i', kind: 'attachment', name: 'a.pdf', mimeType: 'application/pdf', content: new Blob(), about: ['missing'] }]), /absent reference/);
  assert.throws(() => referencePart({ ...reference, target: { kind: 'guess' } }), /unknown reference/);
  for (const path of ['STEP/relative.step', '/work/../outside.step', 'C:\\work\\a.step']) assert.throws(() => referencePart({ ...reference, resource: { ...reference.resource, path } }), /absolute/);
  assert.throws(() => referencePart({ ...reference, target: { kind: 'cad-selector', selectors: ['#not valid'] } }), /invalid CAD/);
});
test('a delivery ledger delivers each operation once, bounds work in flight, and forgets what failed', async () => {
  const ledger = createPromptDeliveryLedger({ maxPending: 2, maxRemembered: 3, busyMessage: 'busy' });
  let starts = 0;
  const release = [];
  const held = () => { starts += 1; return new Promise(resolve => release.push(() => resolve({ status: 'copied', partIds: [] }))); };
  const first = ledger.deliver('a', held);
  assert.equal(ledger.deliver('a', held), first, 'a repeated operation is the one already on its way');
  ledger.deliver('b', held);
  assert.deepEqual(await ledger.deliver('c', held), { status: 'failed', message: 'busy' });
  assert.equal(starts, 2);
  release.forEach(done => done());
  assert.deepEqual(await first, { status: 'copied', partIds: [] });
  assert.equal(ledger.deliver('a', held), first, 'and a delivered one is remembered');
  // A throw or a rejection is a failure, and a failure is forgotten so it can be retried.
  assert.deepEqual(await ledger.deliver('d', () => { throw new Error('no clipboard'); }), { status: 'failed', message: 'no clipboard' });
  await new Promise(resolve => setTimeout(resolve));
  assert.deepEqual(await ledger.deliver('d', () => ({ status: 'added', partIds: ['x'] })), { status: 'added', partIds: ['x'] });
  // Memory is bounded: completed operations make room.
  for (const id of ['e', 'f', 'g']) await ledger.deliver(id, () => ({ status: 'copied', partIds: [] }));
  let restarted = 0;
  await ledger.deliver('a', () => { restarted += 1; return { status: 'copied', partIds: [] }; });
  assert.equal(restarted, 1, 'the oldest completed operation was evicted');
});


test('prompt serialization prefers inline text and preserves references without reading file bytes', async () => {
  const { resolvePromptMessage } = await import('./index.js');
  const small = { id: 'snapshot', kind: 'attachment', name: 'a.snapshot.json', mimeType: 'application/json',
    content: { then() { throw new Error('must not fetch bytes'); } },
    inlineText: Promise.resolve('Snapshot JSON:\n{"jobs":[]}'), path: Promise.resolve('') };
  const context = createPromptContext([textPart('Keep it.'), small]);
  assert.equal(await resolvePromptMessage(context), 'Keep it.\n\nSnapshot JSON:\n{"jobs":[]}');
  assert.equal(await resolvePromptMessage(createPromptContext([textPart('Keep it.'), { ...small,
    inlineText: Promise.resolve(null), path: Promise.resolve('/tmp/a.snapshot.json'), label: 'Snapshot' }])),
    'Keep it.\n\nSnapshot: /tmp/a.snapshot.json');
  await assert.rejects(resolvePromptMessage(createPromptContext([{ ...small, inlineText: Promise.reject(new Error('save failed')) }])), /save failed/);
});
