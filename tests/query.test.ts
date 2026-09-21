import { expect, test } from 'bun:test';
import { queryWindow } from '../src/query';

test('7d is a rolling window with an exclusive end', () => {
  const result = queryWindow({ since: '7d' }, new Date('2026-09-21T12:34:56Z'));
  expect(result.since).toBe('2026-09-14T12:34:56.000Z');
  expect(result.until).toBe('2026-09-21T12:34:56.000Z');
});
test('invalid and reversed windows fail', () => {
  expect(() => queryWindow({ since: 'yesterday' })).toThrow();
  expect(() => queryWindow({ since: '2026-02-30' })).toThrow();
  expect(() => queryWindow({ since: '2026-09-22', until: '2026-09-21' })).toThrow();
});
