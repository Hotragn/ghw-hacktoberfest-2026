# SemVer benchmark report

- **Model:** grok-4.7
- **Start:** 2026-10-15T04:07:00Z
- **End:** 2026-10-15T04:19:32Z
- **Wall-clock:** 12 minutes 32 seconds
- **Lines of code:** `semver.js` 400, `semver.test.js` 340, 740 JavaScript lines total
- **Test results:** 36 passed, 0 failed, 36 total (`node challenge-2-model-benchmark/grok-4.7/semver.test.js`)

## Bugs found and fixed during iteration

1. **Symmetry assertion and `-0`.** The check `compare(a, b) === -compare(b, a)` failed when the two versions were equal. `compareVersions` returned `0`, and unary minus turned that into `-0`. Node's `assert.strictEqual` uses `Object.is`, which treats `0` and `-0` as different. The comparator was fine. The test now requires the two directions to sum to `0`.

2. **`>` and `<=` on partial versions were zero-filled.** `>1.2.x` was implemented as `>1.2.0`, and `<=1.2` as `<=1.2.0`. That lets every `1.2` patch through `>` and keeps `<=` from accepting `1.2.1`. The npm rule advances the first wildcard instead: `>1.2.x` and `>1.2` are `>=1.3.0`, `<=1.2.x` and `<=1.2` are `<1.3.0`, and `>1` is `>=2.0.0`. A cross-check against node-semver 7 caught this. `>=` and `<` on the same partials were already `>=1.2.0` and `<1.2.0`.

3. **Uppercase `V` was accepted as a prefix.** Only a leading lowercase `v` is ignored (`v1.2.3`). `V1.2.3` is now an invalid version, matching node-semver.

4. **Prerelease suffix on a wildcard.** `1.2.x-beta` was rejected. A wildcard with a written patch ignores a valid prerelease suffix, so `1.2.x-beta` is `1.2.x`. `1.2-beta` (no patch component) and `1.2.x-01` (leading zero) stay invalid.

## Limitations

- Prerelease versions match a range only when some comparator in that alternative has a prerelease on the same major.minor.patch. `2.0.0-rc` does not satisfy `<=2.0.0`, `^1.2.3`, `1.2.x`, or `*`. There is no `includePrerelease` switch.
- Caret, tilde, and x-range upper bounds are exclusive releases (`<2.0.0`) rather than `<2.0.0-0`. With the prerelease rule above, those two forms accept the same versions. They would differ if prereleases were included by default.
- An empty range string returns `null`. node-semver treats `""` as `*`.
- `~>` is not accepted as an alias of `~`.
- `compareVersions` requires a full `X.Y.Z` string. Partials such as `1.2` and `1.2.x` are ranges only. Leading zeros, a missing hyphen before a prerelease, an empty build, and a concrete component after a wildcard (`1.x.0`) are invalid.
- Invalid entries in the `versions` array are skipped. An invalid range makes `maxSatisfying` return `null`. `compareVersions` throws.
- Versions that differ only by build metadata compare equal. `maxSatisfying` returns the first of those strings in input order.
- Numeric components are compared as decimal strings, so values past `Number.MAX_SAFE_INTEGER` still order correctly. node-semver rejects those versions. There is no 256-character cap.
- Not implemented: loose mode, coercion, `minSatisfying`, `diff`, `inc`, range intersection, and parentheses.
