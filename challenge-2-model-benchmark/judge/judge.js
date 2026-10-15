'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const semver = require('semver');

const SEED = 20261015;
const COMPARE_CASES = 20000;
const MAX_CASES = 20000;
const MAX_MISMATCHES = 12;

const ROOT = path.resolve(__dirname, '..');
const PRELOAD = path.join(__dirname, 'preload.js');

const MODEL_ORDER = ['composer-2.5', 'claude-sonnet-5.5', 'grok-4.7'];

const MAX_CLASSES = [
  ['exact', 2500],
  ['caret', 2500],
  ['tilde', 2500],
  ['gte', 2000],
  ['lt', 2000],
  ['xrange', 2500],
  ['hyphen', 2000],
  ['gt', 1000],
  ['lte', 1000],
  ['and', 1000],
  ['or', 1000],
];

const PROMPT_CLASSES = new Set(['exact', 'caret', 'tilde', 'gte', 'lt', 'xrange', 'hyphen']);
const WORDS = ['alpha', 'beta', 'rc', 'pre', 'dev'];

function mulberry32(seed) {
  let a = seed >>> 0;
  return function rng() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function percent(agree, total) {
  if (!total) return null;
  return (Math.round((agree * 100000) / total) / 1000).toFixed(3);
}

function lineCount(file) {
  const text = fs.readFileSync(file, 'utf8');
  if (text.length === 0) return 0;
  let n = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (text.charCodeAt(i) === 10) n += 1;
  }
  if (!text.endsWith('\n')) n += 1;
  return n;
}

function discoverModels() {
  const found = fs
    .readdirSync(ROOT, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name !== 'judge')
    .map((entry) => entry.name)
    .filter((name) => {
      const dir = path.join(ROOT, name);
      return fs.existsSync(path.join(dir, 'semver.js')) && fs.existsSync(path.join(dir, 'semver.test.js'));
    });
  const ordered = MODEL_ORDER.filter((name) => found.includes(name));
  for (const name of found.sort()) {
    if (!ordered.includes(name)) ordered.push(name);
  }
  return ordered.map((name) => ({
    name,
    dir: path.join(ROOT, name),
    impl: path.join(ROOT, name, 'semver.js'),
    test: path.join(ROOT, name, 'semver.test.js'),
  }));
}

function normalize(mod) {
  if (mod == null || typeof mod !== 'object') {
    throw new Error('module.exports is not an object');
  }
  const compareAliases = ['compareVersions', 'compare', 'cmp', 'compareVersion'];
  const maxAliases = ['maxSatisfying', 'max_satisfying', 'maxSatisfy', 'maxSat'];
  let compareVersions;
  let maxSatisfying;
  let compareKey = null;
  let maxKey = null;
  for (const key of compareAliases) {
    if (typeof mod[key] === 'function') {
      compareVersions = mod[key];
      compareKey = key;
      break;
    }
  }
  for (const key of maxAliases) {
    if (typeof mod[key] === 'function') {
      maxSatisfying = mod[key];
      maxKey = key;
      break;
    }
  }
  if (!compareVersions || !maxSatisfying) {
    throw new Error('missing compareVersions or maxSatisfying export');
  }
  return {
    compareVersions,
    maxSatisfying,
    exportKeys: Object.keys(mod),
    compareKey,
    maxKey,
    renamed: compareKey !== 'compareVersions' || maxKey !== 'maxSatisfying',
  };
}

function loadModel(model) {
  const resolved = require.resolve(model.impl);
  delete require.cache[resolved];
  const loaded = normalize(require(model.impl));
  return loaded;
}

function parseSummary(text) {
  const matches = [...text.matchAll(/(\d+)\s+passed,\s+(\d+)\s+failed/g)];
  if (matches.length === 0) return null;
  const last = matches[matches.length - 1];
  const passed = Number(last[1]);
  const failed = Number(last[2]);
  return { passed, failed, total: passed + failed };
}

function runTestFile(testPath, implPath) {
  const args = implPath ? ['--require', PRELOAD, testPath] : [testPath];
  const env = { ...process.env };
  if (implPath) env.JUDGE_IMPL = implPath;
  else delete env.JUDGE_IMPL;
  const started = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: path.dirname(testPath),
    env,
    encoding: 'utf8',
    timeout: 60000,
    maxBuffer: 8 * 1024 * 1024,
  });
  const stdout = result.stdout || '';
  const stderr = result.stderr || '';
  const summary = parseSummary(stdout) || parseSummary(`${stdout}\n${stderr}`);
  return {
    passed: summary ? summary.passed : 0,
    failed: summary ? summary.failed : null,
    total: summary ? summary.total : null,
    exitCode: result.status,
    signal: result.signal,
    timedOut: Boolean(result.error && result.error.code === 'ETIMEDOUT'),
    summaryFound: Boolean(summary),
    elapsedMs: Date.now() - started,
    stderrTail: stderr.split('\n').slice(-8).join('\n').slice(-800),
  };
}

function num(rng) {
  const roll = rng();
  if (roll < 0.55) return Math.floor(rng() * 5);
  if (roll < 0.85) return Math.floor(rng() * 15);
  return Math.floor(rng() * 80) + 5;
}

function ident(rng) {
  const roll = rng();
  if (roll < 0.45) return String(Math.floor(rng() * 20));
  const word = WORDS[Math.floor(rng() * WORDS.length)];
  if (roll < 0.75) return word;
  return word + String(Math.floor(rng() * 10));
}

function buildIdent(rng) {
  const count = 1 + Math.floor(rng() * 2);
  const parts = [];
  for (let i = 0; i < count; i += 1) {
    if (rng() < 0.5) parts.push(String(Math.floor(rng() * 1000)));
    else {
      const word = WORDS[Math.floor(rng() * WORDS.length)];
      parts.push(rng() < 0.5 ? word : word + String(Math.floor(rng() * 5)));
    }
  }
  return parts.join('.');
}

function fullVersion(rng, options) {
  const prereleaseRate = options.prereleaseRate;
  const allowBuild = options.build;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    let value = `${num(rng)}.${num(rng)}.${num(rng)}`;
    if (rng() < prereleaseRate) {
      const count = 1 + Math.floor(rng() * 3);
      const ids = [];
      for (let i = 0; i < count; i += 1) ids.push(ident(rng));
      value += `-${ids.join('.')}`;
    }
    if (allowBuild && rng() < 0.4) value += `+${buildIdent(rng)}`;
    if (semver.valid(value)) return value;
  }
  throw new Error('failed to generate a version npm semver accepts');
}

function coreOf(version) {
  const parsed = semver.parse(version);
  if (!parsed) return null;
  return {
    major: parsed.major,
    minor: parsed.minor,
    patch: parsed.patch,
    prerelease: parsed.prerelease.slice(),
    base: `${parsed.major}.${parsed.minor}.${parsed.patch}`,
  };
}

function partial(version, rng) {
  const core = coreOf(version);
  const roll = rng();
  if (roll < 0.5) return core.base;
  if (roll < 0.75) return `${core.major}.${core.minor}`;
  return String(core.major);
}

function shuffle(items, rng) {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    const tmp = items[i];
    items[i] = items[j];
    items[j] = tmp;
  }
  return items;
}

function candidates(seeds, rng) {
  const out = [];
  for (const seed of seeds) {
    const core = coreOf(seed);
    if (!core) continue;
    out.push(core.base);
    if (core.prerelease.length) out.push(seed.split('+')[0]);
    out.push(`${core.base}-rc.1`);
    out.push(`${core.base}-alpha`);
    out.push(`${core.base}-alpha.1`);
    if (core.patch > 0) out.push(`${core.major}.${core.minor}.${core.patch - 1}`);
    out.push(`${core.major}.${core.minor}.${core.patch + 1}`);
    out.push(`${core.major}.${core.minor + 1}.0`);
    out.push(`${core.major + 1}.0.0`);
    if (core.minor > 0) out.push(`${core.major}.${core.minor - 1}.0`);
    if (rng() < 0.45) out.push(`${core.base}+${buildIdent(rng)}`);
    if (rng() < 0.25) out.push(`${core.base}-rc.1+${buildIdent(rng)}`);
  }
  const extra = 3 + Math.floor(rng() * 4);
  for (let i = 0; i < extra; i += 1) {
    out.push(fullVersion(rng, { prereleaseRate: 0.45, build: true }));
  }
  const unique = [];
  const seen = new Set();
  for (const version of out) {
    if (!version || seen.has(version) || !semver.valid(version)) continue;
    seen.add(version);
    unique.push(version);
  }
  return shuffle(unique, rng).slice(0, 12);
}

function caretOf(version, rng) {
  const roll = rng();
  if (roll < 0.6) return `^${version.split('+')[0]}`;
  if (roll < 0.8) return `^${partial(version, rng)}`;
  return `^${coreOf(version).base}`;
}

function tildeOf(version, rng) {
  const roll = rng();
  if (roll < 0.6) return `~${version.split('+')[0]}`;
  if (roll < 0.85) return `~${partial(version, rng)}`;
  return `~${coreOf(version).base}`;
}

function xrangeOf(version, rng) {
  const core = coreOf(version);
  const forms = [
    '*',
    'x',
    'X',
    `${core.major}.x`,
    `${core.major}.X`,
    `${core.major}.*`,
    `${core.major}.${core.minor}.x`,
    `${core.major}.${core.minor}.X`,
    `${core.major}.${core.minor}.*`,
    `${core.major}.${core.minor}`,
    String(core.major),
  ];
  return forms[Math.floor(rng() * forms.length)];
}

function orderedPair(rng) {
  const a = fullVersion(rng, { prereleaseRate: 0.4, build: false });
  const b = fullVersion(rng, { prereleaseRate: 0.4, build: false });
  if (rng() < 0.85 && semver.compare(a, b) > 0) return [b, a];
  return [a, b];
}

function makeRange(kind, rng) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const left = fullVersion(rng, { prereleaseRate: 0.35, build: false });
    const right = fullVersion(rng, { prereleaseRate: 0.35, build: false });
    let range = null;
    let seeds = [left];
    if (kind === 'exact') {
      const bare = left.split('+')[0];
      range = rng() < 0.3 ? `=${bare}` : bare;
    } else if (kind === 'caret') {
      range = caretOf(left, rng);
    } else if (kind === 'tilde') {
      range = tildeOf(left, rng);
    } else if (kind === 'gte') {
      range = `>=${rng() < 0.7 ? left : partial(left, rng)}`;
    } else if (kind === 'lt') {
      range = `<${rng() < 0.7 ? left : partial(left, rng)}`;
    } else if (kind === 'gt') {
      range = `>${rng() < 0.7 ? left : partial(left, rng)}`;
    } else if (kind === 'lte') {
      range = `<=${rng() < 0.7 ? left : partial(left, rng)}`;
    } else if (kind === 'xrange') {
      range = xrangeOf(left, rng);
    } else if (kind === 'hyphen') {
      const pair = orderedPair(rng);
      const lo = rng() < 0.7 ? pair[0] : partial(pair[0], rng);
      const hi = rng() < 0.7 ? pair[1] : partial(pair[1], rng);
      range = `${lo} - ${hi}`;
      seeds = pair;
    } else if (kind === 'and') {
      const pair = orderedPair(rng);
      const op = rng() < 0.5 ? '<' : '<=';
      range = `>=${pair[0]} ${op}${pair[1]}`;
      seeds = pair;
    } else if (kind === 'or') {
      const pair = [left, right];
      const arm = (version) => {
        const roll = rng();
        if (roll < 0.4) return caretOf(version, rng);
        if (roll < 0.7) return tildeOf(version, rng);
        if (roll < 0.85) return xrangeOf(version, rng);
        return version.split('+')[0];
      };
      range = `${arm(pair[0])} || ${arm(pair[1])}`;
      seeds = pair;
    }
    if (range && semver.validRange(range)) {
      return { kind, range, versions: candidates(seeds, rng) };
    }
  }
  throw new Error(`failed to generate a valid ${kind} range`);
}

function generateCases(rng) {
  const compare = [];
  let comparePrerelease = 0;
  let compareBuild = 0;
  for (let i = 0; i < COMPARE_CASES; i += 1) {
    const a = fullVersion(rng, { prereleaseRate: 0.5, build: true });
    const b = fullVersion(rng, { prereleaseRate: 0.5, build: true });
    if (a.includes('-') || b.includes('-')) comparePrerelease += 1;
    if (a.includes('+') || b.includes('+')) compareBuild += 1;
    compare.push([a, b]);
  }
  const max = [];
  const classCounts = {};
  for (const [kind, count] of MAX_CLASSES) {
    classCounts[kind] = count;
    for (let i = 0; i < count; i += 1) max.push(makeRange(kind, rng));
  }
  return {
    compare,
    max,
    comparePrerelease,
    compareBuild,
    classCounts,
  };
}

function sameMax(actual, expected) {
  if (actual == null && expected == null) return { semantic: true, exact: true };
  if (actual == null || expected == null) return { semantic: false, exact: false };
  if (typeof actual !== 'string') return { semantic: false, exact: false };
  const exact = actual === expected;
  try {
    return { semantic: semver.compare(actual, expected) === 0, exact };
  } catch (err) {
    return { semantic: false, exact };
  }
}

function callCompare(fn, a, b) {
  try {
    const value = fn(a, b);
    if (value !== -1 && value !== 0 && value !== 1) {
      return { ok: false, value, error: 'return was not -1, 0, or 1' };
    }
    return { ok: true, value };
  } catch (err) {
    return { ok: false, error: err && err.message ? err.message : String(err) };
  }
}

function callMax(fn, versions, range) {
  try {
    const value = fn(versions.slice(), range);
    if (value != null && typeof value !== 'string') {
      return { ok: false, value: typeof value, error: 'return was not a string or null' };
    }
    return { ok: true, value: value == null ? null : value };
  } catch (err) {
    return { ok: false, error: err && err.message ? err.message : String(err) };
  }
}

function emptyClassStats() {
  const stats = {};
  for (const [kind] of MAX_CLASSES) stats[kind] = { agree: 0, total: 0 };
  return stats;
}

function fuzzModel(loaded, cases) {
  const compareMismatches = [];
  let compareAgree = 0;
  let compareThrows = 0;
  for (const [a, b] of cases.compare) {
    let expected;
    try {
      expected = semver.compare(a, b);
    } catch (err) {
      throw new Error(`npm semver.compare rejected generated pair ${a} ${b}: ${err.message}`);
    }
    const actual = callCompare(loaded.compareVersions, a, b);
    const agree = actual.ok && actual.value === expected;
    if (agree) compareAgree += 1;
    else if (!actual.ok) compareThrows += 1;
    if (!agree && compareMismatches.length < MAX_MISMATCHES) {
      compareMismatches.push({ a, b, npm: expected, impl: actual.ok ? actual.value : null, error: actual.error || null });
    }
  }

  const byClass = emptyClassStats();
  const maxMismatches = [];
  let maxAgree = 0;
  let maxExact = 0;
  let maxThrows = 0;
  let promptAgree = 0;
  let promptTotal = 0;
  let extraAgree = 0;
  let extraTotal = 0;
  for (const item of cases.max) {
    let expected;
    try {
      expected = semver.maxSatisfying(item.versions, item.range);
    } catch (err) {
      throw new Error(`npm semver.maxSatisfying rejected ${item.range}: ${err.message}`);
    }
    const actual = callMax(loaded.maxSatisfying, item.versions, item.range);
    const match = actual.ok ? sameMax(actual.value, expected) : { semantic: false, exact: false };
    byClass[item.kind].total += 1;
    if (match.semantic) {
      maxAgree += 1;
      byClass[item.kind].agree += 1;
    }
    if (match.exact) maxExact += 1;
    if (!actual.ok) maxThrows += 1;
    if (PROMPT_CLASSES.has(item.kind)) {
      promptTotal += 1;
      if (match.semantic) promptAgree += 1;
    } else {
      extraTotal += 1;
      if (match.semantic) extraAgree += 1;
    }
    if (!match.semantic && maxMismatches.length < MAX_MISMATCHES) {
      maxMismatches.push({
        kind: item.kind,
        range: item.range,
        versions: item.versions,
        npm: expected,
        impl: actual.ok ? actual.value : null,
        error: actual.error || null,
      });
    }
  }

  const classReport = {};
  for (const [kind, stats] of Object.entries(byClass)) {
    classReport[kind] = { agree: stats.agree, total: stats.total, pct: percent(stats.agree, stats.total) };
  }

  return {
    compareVersions: {
      agree: compareAgree,
      total: cases.compare.length,
      pct: percent(compareAgree, cases.compare.length),
      throws: compareThrows,
      mismatches: compareMismatches,
    },
    maxSatisfying: {
      agree: maxAgree,
      exact: maxExact,
      total: cases.max.length,
      pct: percent(maxAgree, cases.max.length),
      exactPct: percent(maxExact, cases.max.length),
      throws: maxThrows,
      promptForms: { agree: promptAgree, total: promptTotal, pct: percent(promptAgree, promptTotal) },
      additionalForms: { agree: extraAgree, total: extraTotal, pct: percent(extraAgree, extraTotal) },
      byClass: classReport,
      mismatches: maxMismatches,
    },
  };
}

function main() {
  const models = discoverModels();
  if (models.length === 0) {
    console.error('no model directories found');
    process.exit(1);
  }

  console.log(`generating ${COMPARE_CASES} compare pairs and ${MAX_CASES} range sets (seed ${SEED})`);
  const rng = mulberry32(SEED);
  const cases = generateCases(rng);
  const classSum = Object.values(cases.classCounts).reduce((sum, n) => sum + n, 0);
  if (cases.compare.length !== COMPARE_CASES || classSum !== MAX_CASES) {
    throw new Error(`case count mismatch: compare ${cases.compare.length}, max ${classSum}`);
  }

  const report = {
    seed: SEED,
    npmSemver: require('semver/package.json').version,
    compareCases: COMPARE_CASES,
    maxCases: MAX_CASES,
    comparePairsWithPrerelease: cases.comparePrerelease,
    comparePairsWithBuild: cases.compareBuild,
    maxClassCounts: cases.classCounts,
    agreement: {
      compareVersions: 'same return value in {-1, 0, 1}; a throw or any other return is a mismatch',
      maxSatisfying:
        'both null, or both strings that npm semver.compare treats as equal (build metadata ignored). Exact string equality is recorded separately.',
    },
    models: {},
  };

  for (const model of models) {
    console.log(`\n== ${model.name} ==`);
    const own = runTestFile(model.test, null);
    console.log(`own tests: ${own.passed}/${own.total} exit ${own.exitCode}`);
    const cross = {};
    let crossPassed = 0;
    let crossTotal = 0;
    let crossComplete = true;
    for (const suite of models) {
      const result = runTestFile(suite.test, model.impl);
      cross[suite.name] = result;
      if (result.summaryFound && result.total != null) {
        crossPassed += result.passed;
        crossTotal += result.total;
      } else {
        crossComplete = false;
      }
      console.log(`  vs ${suite.name} tests: ${result.passed}/${result.total} exit ${result.exitCode}`);
    }
    const loaded = loadModel(model);
    const started = Date.now();
    const fuzz = fuzzModel(loaded, cases);
    const fuzzMs = Date.now() - started;
    console.log(
      `fuzz compare ${fuzz.compareVersions.pct}% (${fuzz.compareVersions.agree}/${fuzz.compareVersions.total}), max ${fuzz.maxSatisfying.pct}% (${fuzz.maxSatisfying.agree}/${fuzz.maxSatisfying.total}) in ${fuzzMs}ms`
    );
    report.models[model.name] = {
      loc: lineCount(model.impl),
      testLoc: lineCount(model.test),
      exports: {
        keys: loaded.exportKeys,
        compareKey: loaded.compareKey,
        maxKey: loaded.maxKey,
        renamed: loaded.renamed,
      },
      ownTests: own,
      crossTests: cross,
      crossPassed,
      crossTotal,
      crossComplete,
      fuzzMs,
      fuzz,
    };
  }

  const outPath = path.join(__dirname, 'results.json');
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2) + '\n');
  console.log(`\nwrote ${outPath}`);
}

main();
