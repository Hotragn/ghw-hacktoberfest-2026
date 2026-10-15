'use strict';

/**
 * Parse a SemVer 2.0.0 version string (build metadata ignored for precedence).
 * @returns {{ major: number, minor: number, patch: number, prerelease: string[] | null } | null}
 */
function parseVersion(version) {
  if (typeof version !== 'string') return null;
  let v = version.trim();
  if (!v) return null;

  const plus = v.indexOf('+');
  if (plus !== -1) v = v.slice(0, plus);

  let prerelease = null;
  const dash = v.indexOf('-');
  if (dash !== -1) {
    const pre = v.slice(dash + 1);
    if (!pre) return null;
    prerelease = pre.split('.');
    v = v.slice(0, dash);
  }

  const parts = v.split('.');
  if (parts.length < 1 || parts.length > 3) return null;

  const nums = [];
  for (let i = 0; i < parts.length; i++) {
    if (!/^\d+$/.test(parts[i])) return null;
    nums.push(parseInt(parts[i], 10));
  }
  while (nums.length < 3) nums.push(0);

  return {
    major: nums[0],
    minor: nums[1],
    patch: nums[2],
    prerelease,
  };
}

function compareIdentifiers(a, b) {
  const aNum = /^\d+$/.test(a);
  const bNum = /^\d+$/.test(b);
  if (aNum && bNum) {
    const na = parseInt(a, 10);
    const nb = parseInt(b, 10);
    if (na !== nb) return na < nb ? -1 : 1;
    return 0;
  }
  if (aNum && !bNum) return -1;
  if (!aNum && bNum) return 1;
  const cmp = a < b ? -1 : a > b ? 1 : 0;
  return cmp;
}

function comparePrerelease(a, b) {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;

  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i++) {
    const ai = a[i];
    const bi = b[i];
    if (ai === undefined) return -1;
    if (bi === undefined) return 1;
    const c = compareIdentifiers(ai, bi);
    if (c !== 0) return c;
  }
  return 0;
}

function compareParsed(a, b) {
  if (a.major !== b.major) return a.major < b.major ? -1 : 1;
  if (a.minor !== b.minor) return a.minor < b.minor ? -1 : 1;
  if (a.patch !== b.patch) return a.patch < b.patch ? -1 : 1;
  return comparePrerelease(a.prerelease, b.prerelease);
}

/**
 * @param {string} a
 * @param {string} b
 * @returns {-1 | 0 | 1}
 */
function compareVersions(a, b) {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  if (!pa || !pb) {
    throw new TypeError('Invalid version string');
  }
  return compareParsed(pa, pb);
}

/** Expand partial version in x-ranges to [major, minor, patch] bounds helpers */
function parsePartialVersion(str) {
  const parts = str.split('.').map((p) => {
    if (p === 'x' || p === 'X' || p === '*') return null;
    if (!/^\d+$/.test(p)) return NaN;
    return parseInt(p, 10);
  });
  while (parts.length < 3) parts.push(null);
  if (parts.length > 3 || parts.some((n) => n !== null && Number.isNaN(n))) return null;
  return parts;
}

function satisfiesXRange(version, partial) {
  const v = parseVersion(version);
  if (!v) return false;
  const [maj, min, pat] = partial;
  if (maj !== null && v.major !== maj) return false;
  if (min !== null && v.minor !== min) return false;
  if (pat !== null && v.patch !== pat) return false;
  return true;
}

function caretRange(base) {
  const p = parseVersion(base);
  if (!p || p.prerelease) return null;
  const { major, minor, patch } = p;
  if (major > 0) {
    return { min: p, maxExclusive: { major: major + 1, minor: 0, patch: 0, prerelease: null } };
  }
  if (minor > 0) {
    return {
      min: p,
      maxExclusive: { major, minor: minor + 1, patch: 0, prerelease: null },
    };
  }
  return {
    min: p,
    maxExclusive: { major, minor, patch: patch + 1, prerelease: null },
  };
}

function tildeRange(base) {
  const p = parseVersion(base);
  if (!p || p.prerelease) return null;
  const { major, minor, patch } = p;
  return {
    min: p,
    maxExclusive: { major, minor: minor + 1, patch: 0, prerelease: null },
  };
}

function versionGteParsed(version, bound) {
  const c = compareParsed(version, bound);
  return c >= 0;
}

function versionLtParsed(version, bound) {
  const c = compareParsed(version, bound);
  return c < 0;
}

function satisfiesComparator(versionStr, op, operand) {
  const v = parseVersion(versionStr);
  if (!v) return false;

  operand = operand.trim();

  if (/^[xX*]/.test(operand) || operand.includes('.x') || operand.includes('.X') || operand.includes('.*')) {
    const partial = parsePartialVersion(operand.replace(/\*/g, 'x'));
    if (!partial) return false;
    if (!satisfiesXRange(versionStr, partial)) return false;
    if (op === '=' || op === '') return true;
    return false;
  }

  if (operand.includes('x') || operand.includes('X') || operand.includes('*')) {
    const partial = parsePartialVersion(operand.replace(/\*/g, 'x'));
    if (!partial) return false;
    const ok = satisfiesXRange(versionStr, partial);
    if (op === '=' || op === '') return ok;
    return false;
  }

  if (operand.startsWith('^')) {
    const r = caretRange(operand.slice(1));
    if (!r) return false;
    return versionGteParsed(v, r.min) && versionLtParsed(v, r.maxExclusive);
  }

  if (operand.startsWith('~')) {
    let base = operand.slice(1);
    const partial = parsePartialVersion(base);
    if (partial && partial[2] === null) {
      const p = parseVersion(base.split('.').map((x, i) => (x === 'x' || x === 'X' || x === '*' ? '0' : x)).join('.'));
      if (!p) return false;
      const r = tildeRange(`${p.major}.${p.minor}.${p.patch}`);
      if (!r) return false;
      return versionGteParsed(v, r.min) && versionLtParsed(v, r.maxExclusive);
    }
    const r = tildeRange(base);
    if (!r) return false;
    return versionGteParsed(v, r.min) && versionLtParsed(v, r.maxExclusive);
  }

  const bound = parseVersion(operand);
  if (!bound) return false;

  const cmp = compareParsed(v, bound);
  switch (op) {
    case '':
    case '=':
      return cmp === 0;
    case '>':
      return cmp > 0;
    case '>=':
      return cmp >= 0;
    case '<':
      return cmp < 0;
    case '<=':
      return cmp <= 0;
    default:
      return false;
  }
}

function parseHyphenRange(range) {
  const m = range.match(/^\s*([^\s]+)\s+-\s+([^\s]+)\s*$/);
  if (!m) return null;
  const left = m[1];
  const right = m[2];

  let lowStr = left;
  const leftPartial = parsePartialVersion(left.replace(/\*/g, 'x'));
  if (leftPartial) {
    const [maj, min, pat] = leftPartial;
    lowStr = `${maj ?? 0}.${min ?? 0}.${pat ?? 0}`;
  }
  const low = parseVersion(lowStr);
  if (!low) return null;

  let highStr = right;
  const rightPartial = parsePartialVersion(right.replace(/\*/g, 'x'));
  if (rightPartial) {
    const [maj, min, pat] = rightPartial;
    if (pat !== null) {
      highStr = `${maj}.${min}.${pat}`;
    } else if (min !== null) {
      highStr = `${maj}.${min + 1}.0`;
      return (version) => {
        const v = parseVersion(version);
        if (!v) return false;
        return versionGteParsed(v, low) && versionLtParsed(v, parseVersion(highStr));
      };
    } else if (maj !== null) {
      highStr = `${maj + 1}.0.0`;
      return (version) => {
        const v = parseVersion(version);
        if (!v) return false;
        return versionGteParsed(v, low) && versionLtParsed(v, parseVersion(highStr));
      };
    }
  }

  const high = parseVersion(highStr);
  if (!high) return null;

  return (version) => {
    const v = parseVersion(version);
    if (!v) return false;
    return versionGteParsed(v, low) && compareParsed(v, high) <= 0;
  };
}

function compileRange(range) {
  const r = range.trim();
  if (!r) return () => false;

  const hyphenFn = parseHyphenRange(r);
  if (hyphenFn) return hyphenFn;

  const tokens = r.split(/\s+/).filter(Boolean);
  const comparators = [];

  for (const token of tokens) {
    const cm = token.match(/^(>=|<=|>|<|=)?(.+)$/);
    if (!cm) return () => false;
    let op = cm[1] || '';
    let rest = cm[2];

    if (rest.startsWith('^') || rest.startsWith('~')) {
      comparators.push({ op: '=', operand: rest });
      continue;
    }

    if (/^[\d]*[xX*]/.test(rest) || /\.[xX*]/.test(rest) || rest === '*' || rest === 'x' || rest === 'X') {
      comparators.push({ op: '=', operand: rest });
      continue;
    }

    comparators.push({ op, operand: rest });
  }

  return (version) => {
    for (const { op, operand } of comparators) {
      if (!satisfiesComparator(version, op, operand)) return false;
    }
    return true;
  };
}

/**
 * @param {string[]} versions
 * @param {string} range
 * @returns {string | null}
 */
function maxSatisfying(versions, range) {
  if (!Array.isArray(versions)) return null;
  const satisfies = compileRange(range);
  let best = null;
  let bestParsed = null;

  for (const ver of versions) {
    if (!satisfies(ver)) continue;
    const p = parseVersion(ver);
    if (!p) continue;
    if (bestParsed === null || compareParsed(p, bestParsed) > 0) {
      best = ver;
      bestParsed = p;
    }
  }
  return best;
}

module.exports = { compareVersions, maxSatisfying };
