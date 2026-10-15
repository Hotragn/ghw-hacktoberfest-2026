'use strict';

const assert = require('assert');
const { compareVersions, maxSatisfying } = require('./semver');

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`ok   - ${name}`);
  } catch (err) {
    failed++;
    console.log(`FAIL - ${name}\n       ${err.message.split('\n').join('\n       ')}`);
  }
}

const cmp = (a, b, expected) => assert.strictEqual(compareVersions(a, b), expected, `${a} vs ${b}`);
const max = (versions, range, expected) =>
  assert.strictEqual(maxSatisfying(versions, range), expected, `${range} over [${versions}]`);

test('equal versions', () => cmp('1.2.3', '1.2.3', 0));
test('major/minor/patch ordering', () => {
  cmp('2.0.0', '1.9.9', 1);
  cmp('1.10.0', '1.9.0', 1);
  cmp('1.0.10', '1.0.9', 1);
  cmp('1.0.0', '1.0.1', -1);
});
test('numeric comparison, not lexicographic', () => cmp('1.10.0', '1.2.0', 1));
test('huge numeric components stay exact', () => {
  cmp('9007199254740993.0.0', '9007199254740992.0.0', 1);
  cmp('1.0.0-99999999999999999999', '1.0.0-99999999999999999998', 1);
});
test('prerelease is lower than release', () => {
  cmp('1.0.0-alpha', '1.0.0', -1);
  cmp('1.0.0', '1.0.0-rc.1', 1);
});
test('SemVer spec section 11 precedence chain', () => {
  const chain = [
    '1.0.0-alpha',
    '1.0.0-alpha.1',
    '1.0.0-alpha.beta',
    '1.0.0-beta',
    '1.0.0-beta.2',
    '1.0.0-beta.11',
    '1.0.0-rc.1',
    '1.0.0',
  ];
  for (let i = 0; i < chain.length; i++) {
    for (let j = 0; j < chain.length; j++) {
      cmp(chain[i], chain[j], Math.sign(i - j));
    }
  }
});
test('numeric identifiers have lower precedence than alphanumeric', () => {
  cmp('1.0.0-1', '1.0.0-a', -1);
  cmp('1.0.0-alpha.1', '1.0.0-alpha.a', -1);
  cmp('1.0.0-9', '1.0.0-10', -1);
});
test('alphanumeric identifiers compare in ASCII order', () => {
  cmp('1.0.0-Alpha', '1.0.0-alpha', -1);
  cmp('1.0.0-a-b', '1.0.0-a', 1);
  cmp('1.0.0-alpha', '1.0.0-beta', -1);
});
test('identifier mixing digits and letters is alphanumeric', () => {
  cmp('1.0.0-1a', '1.0.0-2', 1);
  cmp('1.0.0-0a', '1.0.0-1', 1);
});
test('longer prerelease set wins when prefix equal', () => {
  cmp('1.0.0-alpha.1', '1.0.0-alpha', 1);
  cmp('1.0.0-alpha', '1.0.0-alpha.0', -1);
});
test('build metadata is ignored', () => {
  cmp('1.0.0+build.1', '1.0.0+build.2', 0);
  cmp('1.0.0+a', '1.0.0', 0);
  cmp('1.0.0-rc.1+x', '1.0.0-rc.1+y', 0);
  cmp('1.0.0-rc.1+zzz', '1.0.0-rc.2+aaa', -1);
});
test('antisymmetry', () => {
  cmp('1.0.0-alpha.beta', '1.0.0-beta', -1);
  cmp('1.0.0-beta', '1.0.0-alpha.beta', 1);
});
test('invalid versions throw TypeError', () => {
  for (const bad of ['1.2', '1.2.3.4', '01.2.3', '1.02.3', '1.2.3-', '1.2.3-01', '1.2.3-a..b', 'a.b.c', '', '1.2.3+', null, 5]) {
    assert.throws(() => compareVersions(bad, '1.0.0'), TypeError, String(bad));
  }
});
test('leading v and surrounding whitespace are tolerated', () => cmp(' v1.2.3 ', '1.2.3', 0));

test('exact range', () => {
  max(['1.2.2', '1.2.3', '1.2.4'], '1.2.3', '1.2.3');
  max(['1.2.2', '1.2.4'], '1.2.3', null);
  max(['1.2.3'], '=1.2.3', '1.2.3');
});
test('caret >=1.0.0 allows minor/patch bumps only', () => {
  max(['1.2.3', '1.9.0', '2.0.0', '0.9.0'], '^1.2.3', '1.9.0');
  max(['1.2.2', '1.2.3'], '^1.2.3', '1.2.3');
});
test('caret on 0.x pins minor', () => {
  max(['0.2.3', '0.2.9', '0.3.0'], '^0.2.3', '0.2.9');
});
test('caret on 0.0.x pins patch', () => {
  max(['0.0.3', '0.0.4'], '^0.0.3', '0.0.3');
  max(['0.0.2'], '^0.0.3', null);
});
test('caret with partial versions', () => {
  max(['0.0.5', '0.1.0'], '^0.0', '0.0.5');
  max(['0.5.0', '1.0.0'], '^0', '0.5.0');
  max(['1.2.0', '1.9.9', '2.0.0'], '^1.2', '1.9.9');
  max(['1.2.0', '1.9.9', '2.0.0'], '^1.x', '1.9.9');
  max(['0.0.9', '0.1.0'], '^0.0.x', '0.0.9');
});
test('tilde allows patch bumps only', () => {
  max(['1.2.3', '1.2.9', '1.3.0'], '~1.2.3', '1.2.9');
  max(['1.2.0', '1.9.0', '2.0.0'], '~1', '1.9.0');
  max(['1.2.0', '1.2.7', '1.3.0'], '~1.2', '1.2.7');
});
test('comparison operators', () => {
  const vs = ['0.9.9', '1.0.0', '1.5.0', '2.0.0', '2.0.1'];
  max(vs, '>=1.5.0', '2.0.1');
  max(vs, '>1.5.0', '2.0.1');
  max(vs, '<2.0.0', '1.5.0');
  max(vs, '<=2.0.0', '2.0.0');
  max(vs, '>1.0.0 <2.0.0', '1.5.0');
  max(vs, '>=2.0.1', '2.0.1');
  max(vs, '>2.0.1', null);
  max(vs, '<0.9.9', null);
});
test('operators separated from version by whitespace', () => {
  max(['1.0.0', '1.5.0', '2.0.0'], '>= 1.0.0 < 2.0.0', '1.5.0');
});
test('partial versions in comparators', () => {
  max(['1.9.9', '2.0.0', '2.5.0'], '>1', '2.5.0');
  max(['1.9.9', '2.0.0'], '<2', '1.9.9');
  max(['1.2.9', '1.3.0', '1.3.9', '1.4.0'], '<=1.3', '1.3.9');
  max(['1.2.9', '1.3.0'], '>1.2', '1.3.0');
  max(['1.2.9', '1.3.0'], '>=1.3', '1.3.0');
});
test('x-ranges', () => {
  const vs = ['1.1.9', '1.2.0', '1.2.7', '1.3.0', '2.0.0'];
  max(vs, '1.2.x', '1.2.7');
  max(vs, '1.2.X', '1.2.7');
  max(vs, '1.2.*', '1.2.7');
  max(vs, '1.2', '1.2.7');
  max(vs, '1.x', '1.3.0');
  max(vs, '1', '1.3.0');
  max(vs, '*', '2.0.0');
  max(vs, 'x', '2.0.0');
  max(vs, '', '2.0.0');
  max(vs, '3.x', null);
});
test('hyphen ranges', () => {
  const vs = ['1.2.2', '1.2.3', '1.5.0', '2.0.0', '2.0.1'];
  max(vs, '1.2.3 - 2.0.0', '2.0.0');
  max(vs, '1.2.4 - 2.0.0', '2.0.0');
  max(vs, '1.2.3 - 1.9.9', '1.5.0');
});
test('hyphen ranges with partial bounds', () => {
  const vs = ['1.0.0', '1.2.3', '2.0.5', '2.1.0', '3.0.0'];
  max(vs, '1.2 - 2.0', '2.0.5');
  max(vs, '1.2.3 - 2', '2.1.0');
  max(vs, '1 - 2', '2.1.0');
  max(['0.9.0', '1.0.0'], '1 - 1', '1.0.0');
});
test('OR ranges', () => {
  max(['1.0.0', '2.5.0', '3.0.0'], '^1.0.0 || ^2.0.0', '2.5.0');
  max(['1.0.0', '3.0.0'], '<1.0.0 || >=3.0.0', '3.0.0');
});
test('prerelease excluded from ranges by default', () => {
  max(['1.2.3', '1.3.0-beta.1', '2.0.0-alpha'], '^1.2.3', '1.2.3');
  max(['1.3.0-beta.1'], '>=1.0.0', null);
  max(['2.0.0-rc.1'], '*', null);
  max(['1.2.3-beta'], '1.2.x', null);
});
test('prerelease allowed when same tuple appears with prerelease in comparator', () => {
  max(['1.2.3-alpha.1', '1.2.3-alpha.7', '1.2.3-beta', '1.2.4-alpha'], '>=1.2.3-alpha.2', '1.2.3-beta');
  max(['1.2.3-alpha.1', '1.2.3-alpha.3', '1.2.3'], '^1.2.3-alpha.2', '1.2.3');
  max(['1.2.3-alpha.1', '1.2.3-alpha.3'], '^1.2.3-alpha.2', '1.2.3-alpha.3');
  max(['1.2.3-beta.2', '1.2.4-beta.1'], '^1.2.3-beta.1', '1.2.3-beta.2');
});
test('exact prerelease range', () => {
  max(['1.0.0-rc.1', '1.0.0-rc.2', '1.0.0'], '1.0.0-rc.1', '1.0.0-rc.1');
});
test('prerelease upper bound excludes prereleases of the bound', () => {
  max(['1.9.9', '2.0.0-alpha'], '<2.0.0', '1.9.9');
  max(['1.9.9', '2.0.0-alpha'], '^1.0.0', '1.9.9');
  max(['2.0.0-alpha'], '<2.0.0-beta', '2.0.0-alpha');
  max(['2.0.0-beta', '2.0.0-alpha'], '<2.0.0-beta', '2.0.0-alpha');
  max(['1.0.0', '2.0.0-alpha'], '>=1.0.0 <2.0.0-beta', '2.0.0-alpha');
  max(['1.0.0', '2.0.0-beta'], '>=1.0.0 <2.0.0-beta', '1.0.0');
});
test('maxSatisfying ignores build metadata in matching and returns original string', () => {
  max(['1.2.3+build.5', '1.2.2'], '1.2.3', '1.2.3+build.5');
  max(['1.2.3+a', '1.2.3+b'], '^1.0.0', '1.2.3+a');
});
test('maxSatisfying picks highest regardless of input order', () => {
  max(['1.5.0', '1.9.0', '1.1.0', '1.10.0'], '^1.0.0', '1.10.0');
});
test('maxSatisfying skips invalid versions and handles empty input', () => {
  max(['garbage', '1.0.0', '1.x', null], '^1.0.0', '1.0.0');
  max([], '*', null);
});
test('maxSatisfying throws TypeError on invalid ranges', () => {
  for (const bad of ['>=', '^', 'foo', '1.2.3 -', '1.x.3', '^1.2.3.4', '>>1.0.0', '1.2.x-beta', null]) {
    assert.throws(() => maxSatisfying(['1.0.0'], bad), TypeError, String(bad));
  }
});
test('large version numbers in ranges', () => {
  max(['9007199254740993.0.0', '9007199254740992.0.0'], '^9007199254740992.0.0', '9007199254740992.0.0');
  max(['99999999999999999999.0.0'], '>=99999999999999999998.0.0', '99999999999999999999.0.0');
});
test('wildcard comparators', () => {
  max(['1.0.0', '2.0.0'], '>=*', '2.0.0');
  max(['1.0.0', '2.0.0'], '<*', null);
  max(['1.0.0', '2.0.0'], '<=x', '2.0.0');
});
test('contradictory comparator set yields null', () => {
  max(['1.0.0', '2.0.0'], '>2.0.0 <1.0.0', null);
});

console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
process.exit(failed ? 1 : 0);
