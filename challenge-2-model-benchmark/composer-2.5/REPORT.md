# SemVer benchmark — composer-2.5

## Model

`composer-2.5`

## Wall-clock time

| | Timestamp (UTC) |
|---|---|
| Start | 2026-10-15 04:08:01 |
| End | 2026-10-15 04:08:43 |

Duration: ~42 seconds.

## Lines of code

| File | Lines |
|------|------:|
| `semver.js` | 328 |
| `semver.test.js` | 158 |

## Test results

```
node semver.test.js
Results: 27 passed, 0 failed
```

## Bugs found and fixed during iteration

No failing test iterations were required; all 27 cases passed on the first full test run. Unused helper functions (`versionToTuple`, `cmpTuple`) were removed after the initial implementation.

## Self-assessed limitations

- **Range grammar**: Single space-separated AND comparators and simple hyphen ranges only; no `||` (OR) compound ranges.
- **Partial versions in comparators**: Shorthand like `^1.2` (implicit `.0`) is not normalized the way npm semver does.
- **Prerelease in ranges**: Caret/tilde ranges reject prerelease on the range operand; prerelease versions are not matched by `^`/`~` on the candidate side (npm-compatible for releases, not full prerelease-range semantics).
- **Validation**: `compareVersions` throws on invalid strings rather than returning a sentinel; loose or non-SemVer strings in `maxSatisfying` are skipped silently.
- **Hyphen ranges**: Upper bound with `x` wildcards uses simplified expansion (e.g. `1.2.x` as a bound) and may diverge from npm on exotic partial bounds.
- **No `<=`, `>`, lone `=` combos** beyond what tests cover; `=` is only used implicitly or via exact tokens.
