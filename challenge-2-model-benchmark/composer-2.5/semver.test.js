'use strict';

const { compareVersions, maxSatisfying } = require('./semver.js');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`PASS: ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL: ${name}`);
    console.log(`  ${e.message}`);
  }
}

function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(msg || `expected ${expected}, got ${actual}`);
  }
}

test('equal versions', () => {
  assertEqual(compareVersions('1.2.3', '1.2.3'), 0);
});

test('major ordering', () => {
  assertEqual(compareVersions('2.0.0', '1.9.9'), 1);
  assertEqual(compareVersions('1.0.0', '2.0.0'), -1);
});

test('minor and patch ordering', () => {
  assertEqual(compareVersions('1.2.0', '1.1.9'), 1);
  assertEqual(compareVersions('1.0.1', '1.0.0'), 1);
});

test('prerelease lower than release', () => {
  assertEqual(compareVersions('1.0.0', '1.0.0-alpha'), 1);
  assertEqual(compareVersions('1.0.0-alpha', '1.0.0'), -1);
});

test('prerelease identifier numeric vs lexical', () => {
  assertEqual(compareVersions('1.0.0-alpha', '1.0.0-alpha.1'), -1);
  assertEqual(compareVersions('1.0.0-alpha.beta', '1.0.0-alpha.1'), 1);
});

test('numeric prerelease identifiers compared numerically', () => {
  assertEqual(compareVersions('1.0.0-alpha.10', '1.0.0-alpha.2'), 1);
});

test('build metadata ignored in precedence', () => {
  assertEqual(compareVersions('1.0.0+build1', '1.0.0+build2'), 0);
  assertEqual(compareVersions('1.0.0+foo', '1.0.0'), 0);
});

test('longer prerelease loses when prefixes equal', () => {
  assertEqual(compareVersions('1.0.0-alpha', '1.0.0-alpha.1'), -1);
});

test('caret range ^1.2.3', () => {
  assertEqual(maxSatisfying(['1.2.2', '1.2.3', '1.3.0', '2.0.0'], '^1.2.3'), '1.3.0');
});

test('caret range ^0.2.3 caps minor', () => {
  assertEqual(maxSatisfying(['0.2.2', '0.2.3', '0.3.0'], '^0.2.3'), '0.2.3');
  assertEqual(maxSatisfying(['0.2.3', '0.3.0'], '^0.2.3'), '0.2.3');
});

test('tilde range ~1.2.3', () => {
  assertEqual(maxSatisfying(['1.2.2', '1.2.9', '1.3.0'], '~1.2.3'), '1.2.9');
});

test('greater than and less than', () => {
  assertEqual(maxSatisfying(['1.0.0', '1.5.0', '2.0.0'], '>=1.2.0 <2.0.0'), '1.5.0');
});

test('exact version', () => {
  assertEqual(maxSatisfying(['1.0.0', '1.0.1'], '1.0.0'), '1.0.0');
  assertEqual(maxSatisfying(['1.0.0-alpha', '1.0.0'], '1.0.0'), '1.0.0');
});

test('x-range 1.2.x', () => {
  assertEqual(maxSatisfying(['1.1.9', '1.2.0', '1.2.5', '1.3.0'], '1.2.x'), '1.2.5');
});

test('x-range 1.x', () => {
  assertEqual(maxSatisfying(['0.9.0', '1.0.0', '1.9.9', '2.0.0'], '1.x'), '1.9.9');
});

test('hyphen range inclusive', () => {
  assertEqual(
    maxSatisfying(['1.2.2', '1.2.3', '2.0.0', '2.0.1'], '1.2.3 - 2.0.0'),
    '2.0.0'
  );
});

test('hyphen range excludes above high bound', () => {
  assertEqual(maxSatisfying(['2.0.1', '2.1.0'], '1.0.0 - 2.0.0'), null);
});

test('maxSatisfying empty when none match', () => {
  assertEqual(maxSatisfying(['1.0.0'], '^2.0.0'), null);
});

test('maxSatisfying picks highest among many', () => {
  assertEqual(
    maxSatisfying(['1.0.0', '1.1.0', '1.0.5', '1.1.2'], '>=1.0.0'),
    '1.1.2'
  );
});

test('prerelease excluded from caret unless exact', () => {
  assertEqual(maxSatisfying(['1.0.0-alpha', '1.0.0'], '^1.0.0'), '1.0.0');
  assertEqual(maxSatisfying(['1.0.0-alpha'], '^1.0.0'), null);
});

test('compareVersions throws on invalid', () => {
  let threw = false;
  try {
    compareVersions('not-a-version', '1.0.0');
  } catch {
    threw = true;
  }
  assertEqual(threw, true);
});

test('tilde partial ~1.2', () => {
  assertEqual(maxSatisfying(['1.1.9', '1.2.0', '1.2.8', '1.3.0'], '~1.2'), '1.2.8');
});

test('caret major zero patch bump ^0.0.3', () => {
  assertEqual(maxSatisfying(['0.0.2', '0.0.3', '0.0.4'], '^0.0.3'), '0.0.3');
  assertEqual(maxSatisfying(['0.0.3', '0.0.4'], '^0.0.3'), '0.0.3');
});

test('wildcard star x-range', () => {
  assertEqual(maxSatisfying(['0.1.0', '5.0.0'], '*'), '5.0.0');
});

test('build metadata in range candidates', () => {
  assertEqual(maxSatisfying(['1.0.0+meta', '1.0.1'], '<1.0.1'), '1.0.0+meta');
});

test('hyphen with x upper 1.2.x - 1.4.x style partial', () => {
  const r = maxSatisfying(['1.2.0', '1.3.5', '1.4.0', '1.4.1'], '1.2.0 - 1.4.0');
  assertEqual(r, '1.4.0');
});

test('equal prerelease chain', () => {
  assertEqual(compareVersions('1.0.0-rc.1', '1.0.0-rc.1'), 0);
});

console.log('');
console.log(`Results: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
