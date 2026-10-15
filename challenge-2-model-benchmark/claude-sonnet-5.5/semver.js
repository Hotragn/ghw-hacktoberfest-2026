'use strict';

const NUM = '0|[1-9]\\d*';
const VERSION_RE = new RegExp(
  `^[v=\\s]*(${NUM})\\.(${NUM})\\.(${NUM})` +
    `(?:-((?:${NUM}|\\d*[A-Za-z-][0-9A-Za-z-]*)(?:\\.(?:${NUM}|\\d*[A-Za-z-][0-9A-Za-z-]*))*))?` +
    `(?:\\+([0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?\\s*$`
);

const WILD = /^[xX*]$/;
const PARTIAL_RE = new RegExp(
  `^[v=\\s]*(${NUM}|[xX*])(?:\\.(${NUM}|[xX*])(?:\\.(${NUM}|[xX*])` +
    `(?:-((?:${NUM}|\\d*[A-Za-z-][0-9A-Za-z-]*)(?:\\.(?:${NUM}|\\d*[A-Za-z-][0-9A-Za-z-]*))*))?` +
    `(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?)?)?\\s*$`
);

function parse(input) {
  if (typeof input !== 'string') throw new TypeError(`Invalid version: ${String(input)}`);
  const m = VERSION_RE.exec(input);
  if (!m) throw new TypeError(`Invalid version: ${input}`);
  return { major: m[1], minor: m[2], patch: m[3], pre: m[4] ? m[4].split('.') : [] };
}

// Numeric strings are compared without converting to Number so huge values stay exact.
function cmpNumStr(a, b) {
  if (a.length !== b.length) return a.length < b.length ? -1 : 1;
  return a < b ? -1 : a > b ? 1 : 0;
}

const isNumId = (s) => /^\d+$/.test(s);

function cmpPre(a, b) {
  if (!a.length && !b.length) return 0;
  if (!a.length) return 1;
  if (!b.length) return -1;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const x = a[i];
    const y = b[i];
    const xn = isNumId(x);
    const yn = isNumId(y);
    let c;
    if (xn && yn) c = cmpNumStr(x, y);
    else if (xn) c = -1;
    else if (yn) c = 1;
    else c = x < y ? -1 : x > y ? 1 : 0;
    if (c !== 0) return c;
  }
  return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
}

function cmpParsed(a, b) {
  return (
    cmpNumStr(a.major, b.major) ||
    cmpNumStr(a.minor, b.minor) ||
    cmpNumStr(a.patch, b.patch) ||
    cmpPre(a.pre, b.pre)
  );
}

function compareVersions(a, b) {
  return cmpParsed(parse(a), parse(b));
}

const inc = (numStr) => (BigInt(numStr) + 1n).toString();
const v = (major, minor, patch, pre = []) => ({ major, minor, patch, pre });
// "-0" is the lowest possible prerelease, so "<X.Y.Z-0" excludes every X.Y.Z prerelease too.
const lt = (major, minor, patch) => ({ op: '<', ver: v(major, minor, patch, ['0']) });
const gte = (major, minor, patch, pre) => ({ op: '>=', ver: v(major, minor, patch, pre) });

function parsePartial(str) {
  const m = PARTIAL_RE.exec(str);
  if (!m) throw new TypeError(`Invalid range: ${str}`);
  let [, major, minor, patch, pre] = m;
  const isWild = (x) => x === undefined || WILD.test(x);
  if ((isWild(major) && !(isWild(minor) && isWild(patch))) || (isWild(minor) && !isWild(patch))) {
    throw new TypeError(`Invalid range: ${str}`);
  }
  if (major === undefined || WILD.test(major)) {
    major = minor = patch = undefined;
  } else if (minor === undefined || WILD.test(minor)) {
    minor = patch = undefined;
  } else if (patch !== undefined && WILD.test(patch)) {
    patch = undefined;
  }
  if (patch === undefined && m[4] !== undefined) throw new TypeError(`Invalid range: ${str}`);
  return { major, minor, patch, pre: pre ? pre.split('.') : [] };
}

const ANY = [];

// Lower bound of a partial, as comparators (>=).
function lowerOf(p) {
  if (p.major === undefined) return ANY;
  return [gte(p.major, p.minor ?? '0', p.patch ?? '0', p.pre)];
}

// Comparators for "exactly this partial" (x-range semantics).
function xRange(p) {
  if (p.major === undefined) return ANY;
  if (p.minor === undefined) return [gte(p.major, '0', '0'), lt(inc(p.major), '0', '0')];
  if (p.patch === undefined) return [gte(p.major, p.minor, '0'), lt(p.major, inc(p.minor), '0')];
  return [{ op: '=', ver: v(p.major, p.minor, p.patch, p.pre) }];
}

function caret(p) {
  if (p.major === undefined) return ANY;
  const lo = gte(p.major, p.minor ?? '0', p.patch ?? '0', p.pre);
  let hi;
  if (p.major !== '0') hi = lt(inc(p.major), '0', '0');
  else if (p.minor === undefined) hi = lt('1', '0', '0');
  else if (p.minor !== '0') hi = lt('0', inc(p.minor), '0');
  else if (p.patch === undefined) hi = lt('0', '1', '0');
  else hi = lt('0', '0', inc(p.patch));
  return [lo, hi];
}

function tilde(p) {
  if (p.major === undefined) return ANY;
  const lo = gte(p.major, p.minor ?? '0', p.patch ?? '0', p.pre);
  const hi = p.minor === undefined ? lt(inc(p.major), '0', '0') : lt(p.major, inc(p.minor), '0');
  return [lo, hi];
}

const NEVER = [{ op: '<', ver: v('0', '0', '0', ['0']) }];

function primitive(op, p) {
  switch (op) {
    case '^':
      return caret(p);
    case '~':
    case '~>':
      return tilde(p);
    case '':
    case '=':
      return xRange(p);
    case '>=':
      return lowerOf(p);
    case '>':
      if (p.major === undefined) return NEVER;
      if (p.minor === undefined) return [gte(inc(p.major), '0', '0')];
      if (p.patch === undefined) return [gte(p.major, inc(p.minor), '0')];
      return [{ op: '>', ver: v(p.major, p.minor, p.patch, p.pre) }];
    case '<=':
      if (p.major === undefined) return ANY;
      if (p.minor === undefined) return [lt(inc(p.major), '0', '0')];
      if (p.patch === undefined) return [lt(p.major, inc(p.minor), '0')];
      return [{ op: '<=', ver: v(p.major, p.minor, p.patch, p.pre) }];
    case '<':
      if (p.major === undefined) return NEVER;
      if (p.minor === undefined) return [lt(p.major, '0', '0')];
      if (p.patch === undefined) return [lt(p.major, p.minor, '0')];
      return [{ op: '<', ver: v(p.major, p.minor, p.patch, p.pre) }];
    default:
      throw new TypeError(`Invalid range operator: ${op}`);
  }
}

function hyphen(fromStr, toStr) {
  const from = parsePartial(fromStr);
  const to = parsePartial(toStr);
  const out = [...lowerOf(from)];
  if (to.major === undefined) return out;
  if (to.minor === undefined) out.push(lt(inc(to.major), '0', '0'));
  else if (to.patch === undefined) out.push(lt(to.major, inc(to.minor), '0'));
  else out.push({ op: '<=', ver: v(to.major, to.minor, to.patch, to.pre) });
  return out;
}

const HYPHEN_RE = /^\s*(\S+)\s+-\s+(\S+)\s*$/;
const COMPARATOR_RE = /^(\^|~>?|>=|<=|>|<|=)?(.*)$/;

function parseSet(str) {
  const h = HYPHEN_RE.exec(str);
  if (h) return hyphen(h[1], h[2]);
  const normalized = str.replace(/(\^|~>?|>=|<=|>|<|=)\s+/g, '$1').trim();
  if (normalized === '') return ANY;
  const comparators = [];
  for (const token of normalized.split(/\s+/)) {
    const [, op = '', rest] = COMPARATOR_RE.exec(token);
    comparators.push(...primitive(op, parsePartial(rest)));
  }
  return comparators;
}

function parseRange(range) {
  if (typeof range !== 'string') throw new TypeError(`Invalid range: ${String(range)}`);
  return range.split('||').map(parseSet);
}

function testComparator({ op, ver }, version) {
  const c = cmpParsed(version, ver);
  switch (op) {
    case '<':
      return c < 0;
    case '<=':
      return c <= 0;
    case '>':
      return c > 0;
    case '>=':
      return c >= 0;
    default:
      return c === 0;
  }
}

// A prerelease only satisfies a set if some comparator in that set names a prerelease
// of the same major.minor.patch tuple (npm's rule).
function satisfiesSet(set, version) {
  for (const cmp of set) if (!testComparator(cmp, version)) return false;
  if (version.pre.length === 0) return true;
  return set.some(
    ({ ver }) =>
      ver.pre.length > 0 &&
      ver.major === version.major &&
      ver.minor === version.minor &&
      ver.patch === version.patch
  );
}

function maxSatisfying(versions, range) {
  const sets = parseRange(range);
  let best = null;
  let bestParsed = null;
  for (const candidate of versions) {
    let parsed;
    try {
      parsed = parse(candidate);
    } catch {
      continue;
    }
    if (!sets.some((set) => satisfiesSet(set, parsed))) continue;
    if (best === null || cmpParsed(parsed, bestParsed) > 0) {
      best = candidate;
      bestParsed = parsed;
    }
  }
  return best;
}

module.exports = { compareVersions, maxSatisfying };
