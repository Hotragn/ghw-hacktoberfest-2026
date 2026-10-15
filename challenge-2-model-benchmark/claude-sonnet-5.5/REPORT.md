# Benchmark report: SemVer module

- **Model:** claude-sonnet-5.5 (benchmark run, `MODEL=claude-sonnet-5-5`)
- **Task:** dependency-free `semver.js` (`compareVersions`, `maxSatisfying`) plus `semver.test.js`

## Wall-clock time

- Start: 2026-10-15T04:09:59Z (first shell command, after reading the task)
- End: 2026-10-15T04:11:20Z (last test run passing). `REPORT.md` writing and the git/PR steps came after this.
- Elapsed to green tests: about 1 min 21 s, plus roughly 1 to 2 minutes of unmeasured planning and writing before the first command. These are the timestamps from the shell clock.

## Lines of code

| File | Lines |
|---|---|
| `semver.js` | 241 |
| `semver.test.js` | 223 |
| Total | 464 |

## Test results

`node semver.test.js` printed `38 passed, 0 failed, 38 total` (exit code 0).

The 38 test cases cover:

- The full spec section 11 precedence chain, checked pairwise in both directions.
- Numeric versus alphanumeric identifiers, such as `1a` versus `2`, `0a` versus `1`, ASCII case ordering, and `a-b` versus `a`.
- Build metadata being ignored.
- Huge numeric components beyond 2^53, in versions, in prerelease identifiers and in ranges.
- Invalid versions: leading zeros, an empty prerelease, `1.2`, and non-strings.
- Every supported range form:
  - exact
  - `^` (including the 0.x and 0.0.x rules and partials)
  - `~`
  - `>=`, `>`, `<`, `<=`
  - x-ranges (`x`, `X`, `*`, `1.2`, `1`, empty)
  - hyphen ranges, including partial bounds
  - `||`
- The prerelease opt-in rule, and prerelease upper bounds such as `<2.0.0`.
- Invalid-range errors, a contradictory range, and wildcard comparators.

Extra check outside the deliverable. I ran a throwaway differential fuzz against the npm `semver` package, installed in `/tmp` and not committed:

- `compareVersions`: 20,000 random pairs, 0 mismatches.
- `maxSatisfying`: 20,000 random ranges over 400 versions, 5 mismatches. All 5 involve a `0.0.0-<pre>` version and are described under Limitations.

## Bugs found and fixed during iteration

1. **`1.x.3` was accepted as a valid range.** The partial-version parser collapsed a wildcard minor and silently dropped the numeric patch. I now reject any wildcard followed by a non-wildcard component. A test for this exists in the invalid-ranges case.
2. **Two wrong test expectations.** The code was right and my tests were wrong, and I corrected the tests.
   - `<2.0.0-beta` does match `2.0.0-alpha`, because alpha sorts below beta and the comparator names the same `2.0.0` tuple.
   - `>=1.0.0 <2.0.0-beta` has `2.0.0-alpha` as its maximum for the same reason.
   - Both are now asserted in the correct direction, with the `2.0.0-beta` exclusion tested too.

I made no changes to the precedence logic after the first draft.

## Design notes

- Numeric components are compared as digit strings (length, then lexicographic), so values above 2^53 stay exact. `BigInt` is used only to compute the incremented upper bounds.
- Upper bounds are emitted as `<X.Y.Z-0`, so they exclude prereleases of the bound itself, as npm does.
- A prerelease version satisfies a comparator set only if some comparator in that set carries a prerelease on the same `major.minor.patch`. This is npm's rule, not part of SemVer 2.0.0.

## Self-assessed limitations

- **Known divergence from npm `semver`:** with ranges whose lower bound is `0.0.0` (`^0.0.x`, `0.x - 0.0.0-alpha.1`, and similar), npm accepts some `0.0.0-<prerelease>` versions and this module returns `null`. These are 5 mismatches in 20,000 fuzz cases. I did not trace the cause in npm and did not check which behaviour is correct.
- **Hyphen ranges** are only recognised when they make up an entire `||` alternative, for example `1.2.3 - 2.0.0 || ^3`. They cannot be combined with other comparators in the same set. This matches npm.
- **Error handling:** `compareVersions` throws `TypeError` on an invalid version. `maxSatisfying` throws `TypeError` on an invalid range. It silently skips invalid entries in the `versions` array. npm's `maxSatisfying` returns `null` for an invalid range instead.
- **Leniency:** a leading `v` or `=` and surrounding whitespace are accepted on versions, and `~>` is accepted as `~`. Strict SemVer 2.0.0 does not allow these.
- **Not supported:** `includePrerelease` or loose-mode options, coercion of `1.2` or `1` as a plain version, and range intersection and subset operations.
- **Performance:** `maxSatisfying` re-parses every version on each call, which is fine for small lists, and there is no range-parse cache.
- **Test harness:** the tests use a tiny hand-rolled runner with no `node:test`, so output is simple pass/fail lines. Each test case bundles several assertions and stops at its first failure, so the pass count is of cases, not assertions.
