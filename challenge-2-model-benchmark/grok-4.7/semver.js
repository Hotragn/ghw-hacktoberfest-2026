'use strict';

// Dependency-free SemVer 2.0.0 compare plus the npm range forms requested
// for this benchmark: exact, =, >, >=, <, <=, ^, ~, x-ranges, hyphen ranges,
// whitespace AND, and ||. Build metadata is ignored. A prerelease version
// matches a comparator set only when some comparator carries a prerelease on
// the same major.minor.patch (node-semver's default includePrerelease: false).

function cmpNum(a, b) {
  if (a === b) return 0;
  if (a.length !== b.length) return a.length < b.length ? -1 : 1;
  return a < b ? -1 : 1;
}

function inc(num) {
  var digits = num.split('');
  var i = digits.length - 1;
  while (i >= 0) {
    if (digits[i] !== '9') {
      digits[i] = String(digits[i].charCodeAt(0) - 48 + 1);
      return digits.join('');
    }
    digits[i] = '0';
    i -= 1;
  }
  return '1' + digits.join('');
}

function isNumericId(id) {
  return /^[0-9]+$/.test(id);
}

function comparePrerelease(a, b) {
  if (a.length === 0 && b.length === 0) return 0;
  if (a.length === 0) return 1;
  if (b.length === 0) return -1;
  var n = a.length < b.length ? a.length : b.length;
  var i;
  for (i = 0; i < n; i += 1) {
    if (a[i] === b[i]) continue;
    var aNum = isNumericId(a[i]);
    var bNum = isNumericId(b[i]);
    if (aNum && bNum) return cmpNum(a[i], b[i]);
    if (aNum && !bNum) return -1;
    if (!aNum && bNum) return 1;
    return a[i] < b[i] ? -1 : 1;
  }
  if (a.length === b.length) return 0;
  return a.length < b.length ? -1 : 1;
}

function compareParsed(a, b) {
  var c = cmpNum(a.major, b.major);
  if (c !== 0) return c;
  c = cmpNum(a.minor, b.minor);
  if (c !== 0) return c;
  c = cmpNum(a.patch, b.patch);
  if (c !== 0) return c;
  return comparePrerelease(a.prerelease, b.prerelease);
}

function wildcardToNull(value) {
  if (value === 'x' || value === 'X' || value === '*') return null;
  return value;
}

function parsePartial(input) {
  if (typeof input !== 'string') return null;
  var s = input.trim();
  if (s === '') return null;
  if (s === '*' || s === 'x' || s === 'X') {
    return { major: null, minor: null, patch: null, prerelease: [] };
  }
  if (s.charAt(0) === 'v' || s.charAt(0) === 'V') {
    s = s.slice(1);
    if (s === '') return null;
  }

  var plus = s.indexOf('+');
  if (plus !== -1) {
    var build = s.slice(plus + 1);
    if (!/^[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*$/.test(build)) return null;
    s = s.slice(0, plus);
    if (s === '') return null;
  }

  var m = /^(x|X|\*|0|[1-9]\d*)(?:\.(x|X|\*|0|[1-9]\d*))?(?:\.(x|X|\*|0|[1-9]\d*))?(?:-(.+))?$/.exec(s);
  if (!m) return null;

  var major = wildcardToNull(m[1]);
  var minor = m[2] === undefined ? null : wildcardToNull(m[2]);
  var patch = m[3] === undefined ? null : wildcardToNull(m[3]);

  if (major === null) {
    if ((m[2] !== undefined && minor !== null) || (m[3] !== undefined && patch !== null)) {
      return null;
    }
  }
  if (minor === null && m[3] !== undefined && patch !== null) return null;

  var prerelease = [];
  if (m[4] !== undefined) {
    if (major === null || minor === null || patch === null) return null;
    var ids = m[4].split('.');
    var i;
    for (i = 0; i < ids.length; i += 1) {
      if (!/^[0-9A-Za-z-]+$/.test(ids[i])) return null;
      if (isNumericId(ids[i]) && ids[i].length > 1 && ids[i].charAt(0) === '0') return null;
    }
    prerelease = ids;
  }

  return { major: major, minor: minor, patch: patch, prerelease: prerelease };
}

function parseVersion(input) {
  if (typeof input !== 'string') {
    throw new TypeError('version must be a string');
  }
  var partial = parsePartial(input);
  if (!partial || partial.major === null || partial.minor === null || partial.patch === null) {
    throw new Error('invalid semver: ' + input);
  }
  return partial;
}

function comp(op, major, minor, patch, prerelease) {
  return {
    op: op,
    major: major,
    minor: minor,
    patch: patch,
    prerelease: prerelease || []
  };
}

function expandXRange(partial) {
  if (partial.major === null) return [comp('>=', '0', '0', '0', [])];
  if (partial.minor === null) {
    return [
      comp('>=', partial.major, '0', '0', []),
      comp('<', inc(partial.major), '0', '0', [])
    ];
  }
  if (partial.patch === null) {
    return [
      comp('>=', partial.major, partial.minor, '0', []),
      comp('<', partial.major, inc(partial.minor), '0', [])
    ];
  }
  return [comp('=', partial.major, partial.minor, partial.patch, partial.prerelease)];
}

function expandCaret(partial) {
  if (partial.major === null) return [comp('>=', '0', '0', '0', [])];
  if (partial.minor === null) {
    return [
      comp('>=', partial.major, '0', '0', []),
      comp('<', inc(partial.major), '0', '0', [])
    ];
  }
  if (partial.patch === null) {
    if (partial.major === '0') {
      return [
        comp('>=', '0', partial.minor, '0', []),
        comp('<', '0', inc(partial.minor), '0', [])
      ];
    }
    return [
      comp('>=', partial.major, partial.minor, '0', []),
      comp('<', inc(partial.major), '0', '0', [])
    ];
  }
  var lower = comp('>=', partial.major, partial.minor, partial.patch, partial.prerelease);
  if (partial.major === '0') {
    if (partial.minor === '0') {
      return [lower, comp('<', '0', '0', inc(partial.patch), [])];
    }
    return [lower, comp('<', '0', inc(partial.minor), '0', [])];
  }
  return [lower, comp('<', inc(partial.major), '0', '0', [])];
}

function expandTilde(partial) {
  if (partial.major === null) return [comp('>=', '0', '0', '0', [])];
  if (partial.minor === null) {
    return [
      comp('>=', partial.major, '0', '0', []),
      comp('<', inc(partial.major), '0', '0', [])
    ];
  }
  if (partial.patch === null) {
    return [
      comp('>=', partial.major, partial.minor, '0', []),
      comp('<', partial.major, inc(partial.minor), '0', [])
    ];
  }
  return [
    comp('>=', partial.major, partial.minor, partial.patch, partial.prerelease),
    comp('<', partial.major, inc(partial.minor), '0', [])
  ];
}

function expandHyphen(fromRaw, toRaw) {
  var from = parsePartial(fromRaw);
  var to = parsePartial(toRaw);
  if (!from || !to) return null;
  var comps = [];
  if (from.major !== null) {
    var pre = from.minor !== null && from.patch !== null ? from.prerelease : [];
    comps.push(comp(
      '>=',
      from.major,
      from.minor === null ? '0' : from.minor,
      from.patch === null ? '0' : from.patch,
      pre
    ));
  }
  if (to.major !== null) {
    if (to.minor === null) {
      comps.push(comp('<', inc(to.major), '0', '0', []));
    } else if (to.patch === null) {
      comps.push(comp('<', to.major, inc(to.minor), '0', []));
    } else {
      comps.push(comp('<=', to.major, to.minor, to.patch, to.prerelease));
    }
  }
  return comps;
}

function parseComparatorToken(token) {
  if (token.charAt(0) === '^' || token.charAt(0) === '~') {
    var rest = token.slice(1).trim();
    if (!rest) return null;
    var caretPartial = parsePartial(rest);
    if (!caretPartial) return null;
    return token.charAt(0) === '^' ? expandCaret(caretPartial) : expandTilde(caretPartial);
  }

  var op = '=';
  var versionText = token;
  var opMatch = /^(>=|<=|>|<|=)\s*(.+)$/.exec(token);
  if (opMatch) {
    op = opMatch[1];
    versionText = opMatch[2];
  }

  var partial = parsePartial(versionText);
  if (!partial) return null;
  if (op === '=' && (partial.major === null || partial.minor === null || partial.patch === null)) {
    return expandXRange(partial);
  }

  var pre = partial.major !== null && partial.minor !== null && partial.patch !== null
    ? partial.prerelease
    : [];
  return [comp(
    op,
    partial.major === null ? '0' : partial.major,
    partial.minor === null ? '0' : partial.minor,
    partial.patch === null ? '0' : partial.patch,
    pre
  )];
}

function normalizeOperators(alt) {
  return alt.replace(/(>=|<=|>|<|=|\^|~)\s+/g, '$1');
}

function parseAlternative(alt) {
  var normalized = normalizeOperators(alt.trim());
  if (!normalized) return null;
  var hyphen = /^(\S+)\s+-\s+(\S+)$/.exec(normalized);
  if (hyphen) return expandHyphen(hyphen[1], hyphen[2]);
  var tokens = normalized.split(/\s+/);
  var comps = [];
  var i;
  for (i = 0; i < tokens.length; i += 1) {
    var expanded = parseComparatorToken(tokens[i]);
    if (!expanded) return null;
    var j;
    for (j = 0; j < expanded.length; j += 1) comps.push(expanded[j]);
  }
  return comps;
}

function parseRange(range) {
  if (typeof range !== 'string') return null;
  var trimmed = range.trim();
  if (!trimmed) return null;
  var alternatives = trimmed.split(/\s*\|\|\s*/);
  var sets = [];
  var i;
  for (i = 0; i < alternatives.length; i += 1) {
    if (!alternatives[i]) return null;
    var set = parseAlternative(alternatives[i]);
    if (!set) return null;
    sets.push(set);
  }
  return sets;
}

function testComparator(c, version) {
  var cmp = compareParsed(version, c);
  if (c.op === '=') return cmp === 0;
  if (c.op === '>') return cmp > 0;
  if (c.op === '>=') return cmp >= 0;
  if (c.op === '<') return cmp < 0;
  if (c.op === '<=') return cmp <= 0;
  return false;
}

function testSet(set, version) {
  var i;
  for (i = 0; i < set.length; i += 1) {
    if (!testComparator(set[i], version)) return false;
  }
  if (version.prerelease.length > 0) {
    for (i = 0; i < set.length; i += 1) {
      var c = set[i];
      if (
        c.prerelease.length > 0 &&
        c.major === version.major &&
        c.minor === version.minor &&
        c.patch === version.patch
      ) {
        return true;
      }
    }
    return false;
  }
  return true;
}

function satisfiesParsed(version, sets) {
  var i;
  for (i = 0; i < sets.length; i += 1) {
    if (testSet(sets[i], version)) return true;
  }
  return false;
}

function compareVersions(a, b) {
  return compareParsed(parseVersion(a), parseVersion(b));
}

function maxSatisfying(versions, range) {
  if (!Array.isArray(versions)) {
    throw new TypeError('versions must be an array');
  }
  var sets = parseRange(range);
  if (!sets) return null;
  var best = null;
  var bestParsed = null;
  var i;
  for (i = 0; i < versions.length; i += 1) {
    var parsed;
    try {
      parsed = parseVersion(versions[i]);
    } catch (err) {
      continue;
    }
    if (!satisfiesParsed(parsed, sets)) continue;
    if (bestParsed === null || compareParsed(bestParsed, parsed) < 0) {
      best = versions[i];
      bestParsed = parsed;
    }
  }
  return best;
}

module.exports = {
  compareVersions: compareVersions,
  maxSatisfying: maxSatisfying
};
