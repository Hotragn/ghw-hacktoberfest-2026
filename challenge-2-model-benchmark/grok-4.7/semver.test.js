'use strict';

var assert = require('assert');
var semver = require('./semver.js');

var compareVersions = semver.compareVersions;
var maxSatisfying = semver.maxSatisfying;

var passed = 0;
var failed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log('ok ' + name);
  } catch (err) {
    failed += 1;
    console.error('FAIL ' + name);
    console.error(err && err.stack ? err.stack : err);
    process.exitCode = 1;
  }
}

function assertOrder(list) {
  var i;
  var j;
  for (i = 0; i < list.length; i += 1) {
    for (j = 0; j < list.length; j += 1) {
      var expected = i === j ? 0 : (i < j ? -1 : 1);
      var got = compareVersions(list[i], list[j]);
      assert.strictEqual(
        got,
        expected,
        list[i] + ' vs ' + list[j] + ': expected ' + expected + ', got ' + got
      );
    }
  }
}

test('spec precedence chain is totally ordered', function () {
  assertOrder([
    '1.0.0-alpha',
    '1.0.0-alpha.1',
    '1.0.0-alpha.beta',
    '1.0.0-beta',
    '1.0.0-beta.2',
    '1.0.0-beta.11',
    '1.0.0-rc.1',
    '1.0.0'
  ]);
});

test('identical versions compare equal', function () {
  assert.strictEqual(compareVersions('1.2.3', '1.2.3'), 0);
  assert.strictEqual(compareVersions('1.2.3-alpha.1', '1.2.3-alpha.1'), 0);
});

test('build metadata is ignored for equality and ordering', function () {
  assert.strictEqual(compareVersions('1.0.0+build.1', '1.0.0+build.2'), 0);
  assert.strictEqual(compareVersions('1.0.0+20130313144700', '1.0.0'), 0);
  assert.strictEqual(compareVersions('1.0.0-alpha+001', '1.0.0-alpha+002'), 0);
  assert.strictEqual(compareVersions('1.0.0+21AF26D3----117B344092BD', '1.0.0'), 0);
  assert.strictEqual(compareVersions('1.0.0-alpha+001', '1.0.0-alpha.1'), -1);
  assert.strictEqual(compareVersions('1.0.0-beta+exp.sha.5114f85', '1.0.0'), -1);
  assert.strictEqual(compareVersions('1.0.0+build', '1.0.1'), -1);
});

test('numeric prerelease identifiers compare as integers, not strings', function () {
  assert.strictEqual(compareVersions('1.0.0-beta.2', '1.0.0-beta.11'), -1);
  assert.strictEqual(compareVersions('1.0.0-rc.10', '1.0.0-rc.9'), 1);
  assert.strictEqual(compareVersions('1.0.0-1', '1.0.0-2'), -1);
});

test('alphanumeric prerelease identifiers compare as ASCII, not numbers', function () {
  assert.strictEqual(compareVersions('1.0.0-alpha10', '1.0.0-alpha2'), -1);
  assert.strictEqual(compareVersions('1.0.0-alpha.10', '1.0.0-alpha.2'), 1);
  assert.strictEqual(compareVersions('1.0.0-rc', '1.0.0-rc-1'), -1);
  assert.strictEqual(compareVersions('1.0.0-alpha-1', '1.0.0-alpha-2'), -1);
});

test('numeric prerelease identifiers rank below non-numeric ones', function () {
  assert.strictEqual(compareVersions('1.0.0-1', '1.0.0-a'), -1);
  assert.strictEqual(compareVersions('1.0.0-1', '1.0.0-1a'), -1);
  assert.strictEqual(compareVersions('1.0.0-rc.1', '1.0.0-rc.a'), -1);
  assert.strictEqual(compareVersions('1.0.0-alpha.1', '1.0.0-alpha.beta'), -1);
});

test('a longer prerelease list ranks higher when the shared prefix is equal', function () {
  assert.strictEqual(compareVersions('1.0.0-alpha', '1.0.0-alpha.0'), -1);
  assert.strictEqual(compareVersions('1.0.0-rc.1', '1.0.0-rc.1.0'), -1);
  assert.strictEqual(compareVersions('1.0.0-1', '1.0.0-1.0'), -1);
  assert.strictEqual(compareVersions('0.0.0-0', '0.0.0-0.0'), -1);
});

test('prerelease identifiers are case-sensitive ASCII', function () {
  assert.strictEqual(compareVersions('1.0.0-Alpha', '1.0.0-alpha'), -1);
  assert.strictEqual(compareVersions('1.0.0-alpha', '1.0.0-beta'), -1);
  assert.strictEqual(compareVersions('1.0.0-rc', '1.0.0-RC'), 1);
});

test('major and minor outrank patch and prerelease', function () {
  assert.strictEqual(compareVersions('2.0.0-alpha', '1.9.9'), 1);
  assert.strictEqual(compareVersions('1.2.0', '1.1.99'), 1);
  assert.strictEqual(compareVersions('1.0.10', '1.0.9'), 1);
  assert.strictEqual(compareVersions('10.0.0', '9.9.9'), 1);
  assert.strictEqual(compareVersions('0.0.0-alpha', '0.0.0'), -1);
  assert.strictEqual(compareVersions('0.0.0', '0.0.1'), -1);
});

test('numeric components beyond MAX_SAFE_INTEGER compare exactly', function () {
  assert.strictEqual(
    compareVersions('1.0.999999999999999999', '1.0.1000000000000000000'),
    -1
  );
  assert.strictEqual(
    compareVersions('9999999999999999999.0.0', '10000000000000000000.0.0'),
    -1
  );
  assert.strictEqual(
    compareVersions('1.0.0-99999999999999999999', '1.0.0-100000000000000000000'),
    -1
  );
});

test('optional v prefix and surrounding whitespace do not affect precedence', function () {
  assert.strictEqual(compareVersions('  v1.2.3  ', '1.2.3'), 0);
  assert.strictEqual(compareVersions('V1.2.3-alpha+build', '1.2.3-alpha'), 0);
  assert.strictEqual(compareVersions('v2.0.0', '1.9.9'), 1);
});

test('invalid versions throw', function () {
  var bad = ['1.2', '1', '01.0.0', '1.02.0', '1.0.0-01', '1.0.0-', '1.0.0+', '1.0.0-alpha.', '1.0.0-rc..1', 'not', '', '1.2.3.4', '1.2.x'];
  bad.forEach(function (value) {
    assert.throws(function () {
      compareVersions(value, '1.0.0');
    }, /invalid semver/);
  });
  assert.throws(function () {
    compareVersions(1, '1.0.0');
  }, TypeError);
  assert.throws(function () {
    compareVersions(null, '1.0.0');
  }, TypeError);
});

test('compare is symmetric on a mixed set', function () {
  var list = ['0.0.0-0', '0.1.0', '1.0.0-alpha', '1.0.0-alpha.beta', '1.0.0', '1.0.0+zzz', '2.0.0-rc.1'];
  var i;
  var j;
  for (i = 0; i < list.length; i += 1) {
    for (j = 0; j < list.length; j += 1) {
      assert.strictEqual(compareVersions(list[i], list[j]), -compareVersions(list[j], list[i]));
    }
  }
});

test('exact match ignores build metadata and rejects neighbors and prereleases', function () {
  assert.strictEqual(maxSatisfying(['1.2.3+build'], '1.2.3'), '1.2.3+build');
  assert.strictEqual(maxSatisfying(['1.2.3+other'], '1.2.3+build'), '1.2.3+other');
  assert.strictEqual(maxSatisfying(['1.2.4'], '1.2.3'), null);
  assert.strictEqual(maxSatisfying(['1.2.3-0'], '1.2.3'), null);
  assert.strictEqual(maxSatisfying(['1.2.2', '1.2.3', '1.2.4'], '=1.2.3'), '1.2.3');
});

test('caret on 1.x keeps the highest release below the next major', function () {
  assert.strictEqual(
    maxSatisfying(['0.9.9', '1.2.3', '1.2.4-alpha', '1.3.0', '1.9.9', '2.0.0', '2.0.0-rc'], '^1.2.3'),
    '1.9.9'
  );
});

test('caret on 0.x stays inside the left-most non-zero component', function () {
  assert.strictEqual(maxSatisfying(['0.2.3', '0.2.9', '0.2.4-rc', '0.3.0', '1.0.0'], '^0.2.3'), '0.2.9');
  assert.strictEqual(maxSatisfying(['0.0.3', '0.0.4', '0.0.3-alpha', '0.1.0'], '^0.0.3'), '0.0.3');
  assert.strictEqual(maxSatisfying(['0.0.0', '0.0.1', '0.0.0-alpha'], '^0.0.0'), '0.0.0');
});

test('tilde tracks the minor when one is present and the major when it is not', function () {
  assert.strictEqual(maxSatisfying(['1.2.3', '1.2.9', '1.3.0', '1.2.4-rc'], '~1.2.3'), '1.2.9');
  assert.strictEqual(maxSatisfying(['1.0.0', '1.9.9', '2.0.0'], '~1'), '1.9.9');
  assert.strictEqual(maxSatisfying(['0.0.3', '0.0.9', '0.1.0'], '~0.0.3'), '0.0.9');
  assert.strictEqual(maxSatisfying(['0.0.0', '0.0.5', '0.1.0'], '~0.0.0'), '0.0.5');
});

test('caret and tilde with a prerelease allow only that core version prerelease', function () {
  assert.strictEqual(
    maxSatisfying(['1.2.3-beta.1', '1.2.3-beta.2', '1.2.3-beta.10', '1.2.3', '1.2.4-rc', '1.9.0', '2.0.0'], '^1.2.3-beta.2'),
    '1.9.0'
  );
  assert.strictEqual(
    maxSatisfying(['1.2.3-beta.1', '1.2.3-beta.2', '1.2.9', '1.3.0', '1.2.4-alpha'], '~1.2.3-beta.2'),
    '1.2.9'
  );
  assert.strictEqual(maxSatisfying(['1.2.3-beta.10'], '^1.2.3-beta.2'), '1.2.3-beta.10');
  assert.strictEqual(maxSatisfying(['1.2.4-beta'], '^1.2.3-beta.2'), null);
});

test('>= is inclusive and still rejects a lower prerelease of the same version', function () {
  assert.strictEqual(maxSatisfying(['1.2.2', '1.2.3', '1.2.3-rc', '9.0.0'], '>=1.2.3'), '9.0.0');
  assert.strictEqual(maxSatisfying(['1.2.3'], '>= 1.2.3'), '1.2.3');
});

test('< is exclusive and does not admit a prerelease of the excluded version', function () {
  assert.strictEqual(maxSatisfying(['1.9.9', '2.0.0', '2.0.0-rc', '1.0.0'], '<2.0.0'), '1.9.9');
  assert.strictEqual(maxSatisfying(['1.0.0-rc', '0.9.0'], '<1.0.0'), '0.9.0');
});

test('> and <= use the same precedence rules', function () {
  assert.strictEqual(maxSatisfying(['1.2.3', '1.2.4', '1.2.5'], '>1.2.3'), '1.2.5');
  assert.strictEqual(maxSatisfying(['1.2.2', '1.2.3', '1.2.4'], '<=1.2.3'), '1.2.3');
  assert.strictEqual(maxSatisfying(['1.2.3-rc'], '<=1.2.3'), null);
});

test('x-ranges and partial versions stay inside the first omitted component', function () {
  assert.strictEqual(maxSatisfying(['1.2.0', '1.2.5', '1.2.10', '1.3.0', '1.2.4-alpha'], '1.2.x'), '1.2.10');
  assert.strictEqual(maxSatisfying(['1.2.0', '1.2.9', '1.3.0'], '1.2.*'), '1.2.9');
  assert.strictEqual(maxSatisfying(['1.2.0', '1.2.9', '1.3.0'], '1.2.X'), '1.2.9');
  assert.strictEqual(maxSatisfying(['1.1.9', '1.2.0', '1.2.8', '1.3.0'], '1.2'), '1.2.8');
  assert.strictEqual(maxSatisfying(['0.9.0', '1.0.0', '1.9.9', '2.0.0'], '1.x'), '1.9.9');
  assert.strictEqual(maxSatisfying(['0.9.0', '1.4.0', '2.0.0'], '1'), '1.4.0');
  assert.strictEqual(maxSatisfying(['0.0.0', '1.0.0-alpha', '2.0.0', '3.0.0-rc'], '*'), '2.0.0');
  assert.strictEqual(maxSatisfying(['1.0.0', '2.0.0-rc.1'], 'x'), '1.0.0');
});

test('^1.2.x reaches the next major while ~1.2.x and 1.2.x do not', function () {
  var versions = ['1.2.0', '1.2.9', '1.5.0', '2.0.0'];
  assert.strictEqual(maxSatisfying(versions, '^1.2.x'), '1.5.0');
  assert.strictEqual(maxSatisfying(versions, '~1.2.x'), '1.2.9');
  assert.strictEqual(maxSatisfying(versions, '1.2.x'), '1.2.9');
  assert.strictEqual(maxSatisfying(['0.0.0', '0.0.9', '0.1.0'], '^0.0.x'), '0.0.9');
  assert.strictEqual(maxSatisfying(['0.2.0', '0.2.9', '0.3.0'], '^0.2.x'), '0.2.9');
});

test('hyphen range is inclusive at both full ends', function () {
  assert.strictEqual(
    maxSatisfying(['1.2.2', '1.2.3', '1.9.0', '2.0.0', '2.0.1', '2.0.0-rc'], '1.2.3 - 2.0.0'),
    '2.0.0'
  );
  assert.strictEqual(maxSatisfying(['1.2.3'], '1.2.3 - 2.0.0'), '1.2.3');
  assert.strictEqual(maxSatisfying(['2.0.0-rc'], '1.2.3 - 2.0.0'), null);
});

test('partial hyphen ends expand to the next omitted component', function () {
  assert.strictEqual(maxSatisfying(['1.2.3', '2.9.9', '3.0.0', '2.0.0-alpha'], '1.2.3 - 2'), '2.9.9');
  assert.strictEqual(maxSatisfying(['2.0.9', '2.1.0', '1.2.3'], '1.2.3 - 2.0'), '2.0.9');
  assert.strictEqual(maxSatisfying(['1.1.9', '1.2.0', '2.0.0', '2.0.1'], '1.2 - 2.0.0'), '2.0.0');
  assert.strictEqual(maxSatisfying(['1.2.0', '2.3.9', '2.4.0'], '1.2 - 2.3'), '2.3.9');
});

test('hyphen ranges with prerelease bounds keep that tuple only', function () {
  assert.strictEqual(
    maxSatisfying(['1.2.3-alpha', '1.2.3-alpha.1', '1.2.3-beta', '1.2.3', '1.2.3-rc', '1.2.4'], '1.2.3-alpha - 1.2.3-beta'),
    '1.2.3-beta'
  );
  assert.strictEqual(maxSatisfying(['1.2.3-alpha.0'], '1.2.3-alpha - 1.2.3-beta'), '1.2.3-alpha.0');
  assert.strictEqual(maxSatisfying(['2.0.0-rc.1', '2.0.0-rc.2', '2.0.0'], '1.0.0 - 2.0.0-rc.1'), '2.0.0-rc.1');
});

test('a prerelease comparator does not unlock other core versions', function () {
  assert.strictEqual(
    maxSatisfying(['1.2.3-alpha', '1.2.3-beta', '1.2.3', '1.2.4-alpha', '1.2.4'], '>=1.2.3-alpha <1.2.4'),
    '1.2.3'
  );
  assert.strictEqual(
    maxSatisfying(['1.0.0-alpha', '1.0.0-rc.1', '1.0.0-rc.2', '1.0.0'], '>=1.0.0-alpha <1.0.0'),
    '1.0.0-rc.2'
  );
  assert.strictEqual(maxSatisfying(['1.5.0-alpha'], '>=1.2.3-alpha'), null);
});

test('whitespace AND and || OR combine comparators', function () {
  assert.strictEqual(maxSatisfying(['1.2.3', '1.4.9', '1.4.9-rc', '1.5.0'], '>=1.2.3 <1.5.0'), '1.4.9');
  assert.strictEqual(maxSatisfying(['2.1.0', '1.2.9', '2.0.0'], '1.2.x || 2.0.0'), '2.0.0');
  assert.strictEqual(maxSatisfying(['1.0.0', '2.5.0', '3.0.0'], '1.x || >=2.0.0 <2.6.0'), '2.5.0');
  assert.strictEqual(maxSatisfying(['1.2.3', '1.9.0'], '>= 1.2.3   <  2.0.0'), '1.9.0');
});

test('maxSatisfying keeps the original string and the first build-equal maximum', function () {
  assert.strictEqual(maxSatisfying(['v1.2.3', 'v1.2.4', 'v2.0.0'], '^1.2.0'), 'v1.2.4');
  assert.strictEqual(maxSatisfying(['1.2.3+b', '1.2.3+a'], '1.2.3'), '1.2.3+b');
  assert.strictEqual(maxSatisfying(['1.2.3+99', '1.2.4+0'], '^1.2.3'), '1.2.4+0');
});

test('maxSatisfying skips invalid entries, ignores order, and does not mutate input', function () {
  var versions = ['nope', '1.0.0', '01.2.3', '1.2.0', '1.1.5'];
  var copy = versions.slice();
  assert.strictEqual(maxSatisfying(versions, '^1.0.0'), '1.2.0');
  assert.deepStrictEqual(versions, copy);
  assert.strictEqual(maxSatisfying(['2.0.0', '1.0.0', '1.9.0'], '1.x'), '1.9.0');
});

test('maxSatisfying returns null when nothing matches or the range is invalid', function () {
  assert.strictEqual(maxSatisfying([], '*'), null);
  assert.strictEqual(maxSatisfying(['2.0.0'], '^1.0.0'), null);
  assert.strictEqual(maxSatisfying(['1.0.0'], 'not a range'), null);
  assert.strictEqual(maxSatisfying(['1.0.0'], ''), null);
  assert.strictEqual(maxSatisfying(['1.0.0'], '^'), null);
  assert.strictEqual(maxSatisfying(['1.0.0'], '1.2.3 -'), null);
  assert.strictEqual(maxSatisfying(['1.0.0'], null), null);
  assert.throws(function () {
    maxSatisfying('1.0.0', '1.0.0');
  }, TypeError);
});

test('hyphen with extra spaces and v prefixes still includes both ends', function () {
  assert.strictEqual(maxSatisfying(['v1.2.3', 'v2.0.0', 'v2.0.1'], 'v1.2.3  -  v2.0.0'), 'v2.0.0');
});

test('build metadata on a hyphen endpoint does not change the bounds', function () {
  assert.strictEqual(maxSatisfying(['1.0.0+a', '1.5.0+b', '2.0.0+c', '2.0.1'], '1.0.0+build - 2.0.0+build'), '2.0.0+c');
});

test('an exact prerelease version matches only itself, ignoring build', function () {
  assert.strictEqual(maxSatisfying(['1.2.3-alpha+1', '1.2.3-alpha.1', '1.2.3'], '1.2.3-alpha'), '1.2.3-alpha+1');
  assert.strictEqual(maxSatisfying(['1.2.3-2.0.0'], '1.2.3-2.0.0'), '1.2.3-2.0.0');
  assert.strictEqual(compareVersions('1.2.3-2.0.0', '1.2.3-2.0.1'), -1);
});

console.log('');
console.log(passed + ' passed, ' + failed + ' failed, ' + (passed + failed) + ' total');
