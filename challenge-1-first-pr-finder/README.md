# First PR Finder

A single-page app that scores how ready a GitHub repository is for a first-time contributor, then recommends three starter issues.

Paste `owner/name` or a GitHub URL. The app calls the public GitHub REST API from the browser and builds a **Contributor-Readiness Score** from 0 to 100. Each row shows the points and the rule that produced them:

- README, CONTRIBUTING, LICENSE, CODE_OF_CONDUCT, and issue templates
- Open issues labeled good first issue, help wanted, or hacktoberfest
- How recently the repository was pushed
- Median time until an owner, member, or collaborator comments on a small sample of recent issues and pull requests
- How often recently closed pull requests were merged

The top three recommendations are unassigned issues with those starter labels, preferring few comments and a recent open date. Each card includes a one-line reason.

An optional personal access token is stored only in `localStorage`. It is sent to `api.github.com` and is never written into the share URL (`?repo=owner/name`).

## Run

No install and no build step. From this folder:

```bash
python3 -m http.server 8765
```

Open [http://localhost:8765/?repo=facebook/react](http://localhost:8765/?repo=facebook/react).

Opening `index.html` as a `file://` page usually blocks the GitHub requests. Use a local static server.

Unauthenticated GitHub usage allows about 60 requests an hour. One lookup uses around a dozen. A token with public repository read access raises that limit. The page explains rate limits, missing repositories, and empty starter-issue lists in the result.

## Tests

The score is a pure function in `scoring.js`. From this folder:

```bash
node scoring.test.js
```

No dependencies.
