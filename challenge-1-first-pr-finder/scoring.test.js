"use strict";

var assert = require("assert");
var scoring = require("./scoring");

var passed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log("ok " + name);
  } catch (err) {
    console.error("FAIL " + name);
    console.error(err && err.stack ? err.stack : err);
    process.exitCode = 1;
  }
}

function row(result, id) {
  for (var i = 0; i < result.breakdown.length; i++) {
    if (result.breakdown[i].id === id) return result.breakdown[i];
  }
  throw new Error("missing row " + id);
}

test("weights sum to 100", function () {
  var sum = 0;
  Object.keys(scoring.WEIGHTS).forEach(function (key) {
    sum += scoring.WEIGHTS[key];
  });
  assert.strictEqual(sum, 100);
});

test("parseRepoInput accepts owner/name and common GitHub URLs", function () {
  assert.deepStrictEqual(scoring.parseRepoInput("  facebook/react  "), { owner: "facebook", repo: "react" });
  assert.deepStrictEqual(scoring.parseRepoInput("https://github.com/facebook/react"), { owner: "facebook", repo: "react" });
  assert.deepStrictEqual(scoring.parseRepoInput("https://github.com/facebook/react/"), { owner: "facebook", repo: "react" });
  assert.deepStrictEqual(scoring.parseRepoInput("https://github.com/facebook/react.git"), { owner: "facebook", repo: "react" });
  assert.deepStrictEqual(scoring.parseRepoInput("https://github.com/facebook/react/tree/main/packages"), { owner: "facebook", repo: "react" });
  assert.deepStrictEqual(scoring.parseRepoInput("https://www.github.com/facebook/react?tab=readme"), { owner: "facebook", repo: "react" });
  assert.deepStrictEqual(scoring.parseRepoInput("HTTPS://GitHub.com/Facebook/React"), { owner: "Facebook", repo: "React" });
  assert.deepStrictEqual(scoring.parseRepoInput("github.com/nodejs/node"), { owner: "nodejs", repo: "node" });
  assert.deepStrictEqual(scoring.parseRepoInput("git@github.com:vercel/next.js.git"), { owner: "vercel", repo: "next.js" });
});

test("parseRepoInput rejects non-repos", function () {
  assert.strictEqual(scoring.parseRepoInput(""), null);
  assert.strictEqual(scoring.parseRepoInput("   "), null);
  assert.strictEqual(scoring.parseRepoInput(null), null);
  assert.strictEqual(scoring.parseRepoInput("facebook"), null);
  assert.strictEqual(scoring.parseRepoInput("facebook/react/issues"), null);
  assert.strictEqual(scoring.parseRepoInput("https://gitlab.com/facebook/react"), null);
  assert.strictEqual(scoring.parseRepoInput("https://github.com/facebook"), null);
  assert.strictEqual(scoring.parseRepoInput("git@gitlab.com:facebook/react.git"), null);
  assert.strictEqual(scoring.parseRepoInput("face book/react"), null);
  assert.strictEqual(scoring.parseRepoInput("facebook/."), null);
  assert.strictEqual(scoring.parseRepoInput("../etc"), null);
  assert.strictEqual(scoring.parseRepoInput("javascript:alert(1)"), null);
});

test("classifyLabel and groupStarterLabels prefer canonical names", function () {
  assert.strictEqual(scoring.classifyLabel("Good First Issue"), "goodFirst");
  assert.strictEqual(scoring.classifyLabel("good-first-issue"), "goodFirst");
  assert.strictEqual(scoring.classifyLabel("beginner-friendly"), "goodFirst");
  assert.strictEqual(scoring.classifyLabel("first-timers-only"), "goodFirst");
  assert.strictEqual(scoring.classifyLabel("Help Wanted"), "helpWanted");
  assert.strictEqual(scoring.classifyLabel("hacktoberfest"), "hacktoberfest");
  assert.strictEqual(scoring.classifyLabel("hacktoberfest-2025"), "hacktoberfest");
  assert.strictEqual(scoring.classifyLabel("hacktoberfest-accepted"), null);
  assert.strictEqual(scoring.classifyLabel("bug"), null);

  var grouped = scoring.groupStarterLabels([
    { name: "bug" },
    { name: "good-first-issue" },
    { name: "Good First Issue" },
    { name: "help wanted" },
    { name: "hacktoberfest-accepted" },
    { name: "hacktoberfest" },
  ]);
  assert.deepStrictEqual(grouped, {
    goodFirst: "Good First Issue",
    helpWanted: "help wanted",
    hacktoberfest: "hacktoberfest",
  });
  assert.deepStrictEqual(scoring.groupStarterLabels([{ name: "docs" }]), {
    goodFirst: null,
    helpWanted: null,
    hacktoberfest: null,
  });
});

test("median handles odd, even, empty, and does not mutate input", function () {
  var values = [10, 2, 4];
  assert.strictEqual(scoring.median(values), 4);
  assert.deepStrictEqual(values, [10, 2, 4]);
  assert.strictEqual(scoring.median([1, 3]), 2);
  assert.strictEqual(scoring.median([1, 2, 3, 4]), 2.5);
  assert.strictEqual(scoring.median([8]), 8);
  assert.strictEqual(scoring.median([]), null);
  assert.strictEqual(scoring.median(["nope", null]), null);
});

test("firstMaintainerResponseHours skips bots, the author, and non-maintainers", function () {
  var hours = scoring.firstMaintainerResponseHours("2026-01-01T00:00:00Z", [
    { created_at: "2026-01-01T01:00:00Z", author_association: "NONE", user: { login: "bot", type: "Bot" } },
    { created_at: "2026-01-01T02:00:00Z", author_association: "NONE", user: { login: "ada", type: "User" } },
    { created_at: "2026-01-01T03:00:00Z", author_association: "CONTRIBUTOR", user: { login: "bea", type: "User" } },
    { created_at: "2026-01-01T05:00:00Z", author_association: "MEMBER", user: { login: "cy", type: "User" } },
    { created_at: "2026-01-01T04:00:00Z", author_association: "OWNER", user: { login: "dee", type: "User" } },
  ], "ada");
  assert.strictEqual(hours, 4);

  assert.strictEqual(scoring.firstMaintainerResponseHours("2026-01-01T00:00:00Z", [
    { created_at: "2026-01-01T02:00:00Z", author_association: "NONE", user: { login: "ada", type: "User" } },
  ], "ada"), null);

  var clamped = scoring.firstMaintainerResponseHours("2026-01-02T00:00:00Z", [
    { created_at: "2026-01-01T00:00:00Z", author_association: "OWNER", user: { login: "dee", type: "User" } },
  ], "ada");
  assert.strictEqual(clamped, 0);
  assert.strictEqual(scoring.firstMaintainerResponseHours("nope", [], "ada"), null);
});

test("empty signals score 0 and a full set scores 100", function () {
  var empty = scoring.computeReadinessScore({});
  assert.strictEqual(empty.score, 0);
  assert.strictEqual(empty.verdict.id, "hard");
  assert.strictEqual(empty.breakdown.reduce(function (sum, item) { return sum + item.points; }, 0), 0);
  assert.ok(row(empty, "readme").detail.indexOf("was not found") !== -1);

  var perfect = scoring.computeReadinessScore({
    hasReadme: true,
    hasContributing: true,
    hasLicense: true,
    hasCodeOfConduct: true,
    hasIssueTemplates: true,
    goodFirstIssueCount: 3,
    goodFirstLabelName: "good first issue",
    helpWantedCount: 3,
    helpWantedLabelName: "help wanted",
    hacktoberfestCount: 3,
    hacktoberfestLabelName: "hacktoberfest",
    daysSinceLastPush: 1,
    medianResponseHours: 5,
    responseSampleSize: 4,
    responseThreadsChecked: 5,
    mergedPullRequests: 24,
    closedPullRequestSample: 30,
  });
  assert.strictEqual(perfect.score, 100);
  assert.strictEqual(perfect.verdict.id, "ready");
  assert.strictEqual(perfect.verdict.title, "Ready for a first contribution");
  assert.deepStrictEqual(perfect.breakdown.map(function (item) { return item.id; }), [
    "readme", "contributing", "license", "codeOfConduct", "issueTemplates",
    "starterIssues", "activity", "response", "mergeRatio",
  ]);
  assert.strictEqual(perfect.breakdown.reduce(function (sum, item) { return sum + item.max; }, 0), 100);
  assert.strictEqual(perfect.breakdown.reduce(function (sum, item) { return sum + item.points; }, 0), 100);
  perfect.breakdown.forEach(function (item) {
    assert.ok(item.points <= item.max);
    assert.ok(item.detail.length > 10);
  });
  assert.strictEqual(row(perfect, "readme").detail, "README is present. That earns 10 of 10.");
  assert.ok(row(perfect, "starterIssues").detail.indexOf('Label "good first issue": 3 open issues.') !== -1);
  assert.ok(row(perfect, "starterIssues").detail.indexOf("A combined total of 9 or more earns 15 of 15.") !== -1);
  assert.ok(row(perfect, "starterIssues").detail.indexOf("counted in each tally") !== -1);
  assert.strictEqual(row(perfect, "activity").detail, "Last push was 1 day ago. A push within 7 days earns 15 of 15.");
  assert.ok(row(perfect, "response").detail.indexOf("Median first maintainer comment was 5 hours across 4 threads") !== -1);
  assert.ok(row(perfect, "response").detail.indexOf("1 other sampled thread") !== -1);
  assert.strictEqual(
    row(perfect, "mergeRatio").detail,
    "24 of 30 recently updated closed pull requests were merged (80%). A merge ratio of at least 80% earns 10 of 10."
  );
});

test("starter, activity, response, and merge bands sit on their boundaries", function () {
  function starterPoints(counts) {
    return row(scoring.computeReadinessScore({
      goodFirstIssueCount: counts[0],
      goodFirstLabelName: "good first issue",
      helpWantedCount: counts[1],
      helpWantedLabelName: counts[1] ? "help wanted" : "",
      hacktoberfestCount: counts[2],
      hacktoberfestLabelName: counts[2] ? "hacktoberfest" : "",
    }), "starterIssues").points;
  }
  assert.strictEqual(starterPoints([0, 0, 0]), 0);
  assert.strictEqual(starterPoints([1, 0, 0]), 4);
  assert.strictEqual(starterPoints([2, 0, 0]), 8);
  assert.strictEqual(starterPoints([3, 0, 0]), 8);
  assert.strictEqual(starterPoints([4, 0, 0]), 12);
  assert.strictEqual(starterPoints([8, 0, 0]), 12);
  assert.strictEqual(starterPoints([9, 0, 0]), 15);
  assert.strictEqual(starterPoints([-4, 0, 0]), 0);

  function activity(days) {
    return row(scoring.computeReadinessScore({ daysSinceLastPush: days }), "activity").points;
  }
  assert.strictEqual(activity(0), 15);
  assert.strictEqual(activity(7), 15);
  assert.strictEqual(activity(7.1), 12);
  assert.strictEqual(activity(30), 12);
  assert.strictEqual(activity(30.1), 8);
  assert.strictEqual(activity(90), 8);
  assert.strictEqual(activity(180), 4);
  assert.strictEqual(activity(365), 2);
  assert.strictEqual(activity(365.1), 0);
  assert.strictEqual(activity(null), 0);
  assert.strictEqual(activity(-1), 15);

  function response(hours) {
    return row(scoring.computeReadinessScore({
      medianResponseHours: hours,
      responseSampleSize: 2,
      responseThreadsChecked: 2,
    }), "response").points;
  }
  assert.strictEqual(response(0), 10);
  assert.strictEqual(response(24), 10);
  assert.strictEqual(response(24.1), 8);
  assert.strictEqual(response(72), 8);
  assert.strictEqual(response(168), 6);
  assert.strictEqual(response(336), 4);
  assert.strictEqual(response(720), 2);
  assert.strictEqual(response(721), 1);
  assert.strictEqual(response(null), 0);

  function merge(merged, sample) {
    return row(scoring.computeReadinessScore({
      mergedPullRequests: merged,
      closedPullRequestSample: sample,
    }), "mergeRatio");
  }
  assert.strictEqual(merge(30, 30).points, 10);
  assert.strictEqual(merge(24, 30).points, 10);
  assert.strictEqual(merge(23, 30).points, 8);
  assert.ok(merge(23, 30).detail.indexOf("76.7%") !== -1);
  assert.strictEqual(merge(18, 30).points, 8);
  assert.strictEqual(merge(12, 30).points, 6);
  assert.strictEqual(merge(6, 30).points, 3);
  assert.strictEqual(merge(1, 30).points, 1);
  assert.strictEqual(merge(0, 30).points, 0);
  assert.strictEqual(merge(0, 0).points, 0);
});

test("unknown checks say they could not be loaded", function () {
  var result = scoring.computeReadinessScore({
    known: {
      readme: false,
      contributing: false,
      license: false,
      codeOfConduct: false,
      issueTemplates: false,
    },
    starterCountsKnown: false,
    mergeSampleKnown: false,
    responseKnown: false,
  });
  assert.strictEqual(result.score, 0);
  assert.ok(row(result, "readme").detail.indexOf("could not be checked") !== -1);
  assert.ok(row(result, "issueTemplates").detail.indexOf("could not be checked") !== -1);
  assert.ok(row(result, "starterIssues").detail.indexOf("could not be counted") !== -1);
  assert.ok(row(result, "response").detail.indexOf("could not be loaded") !== -1);
  assert.ok(row(result, "mergeRatio").detail.indexOf("could not be loaded") !== -1);
});

test("verdict bands", function () {
  var thin = scoring.computeReadinessScore({
    goodFirstIssueCount: 9,
    goodFirstLabelName: "good first issue",
    daysSinceLastPush: 1,
  });
  assert.strictEqual(thin.score, 30);
  assert.strictEqual(thin.verdict.id, "thin");

  var walkable = scoring.computeReadinessScore({
    hasReadme: true,
    hasContributing: true,
    hasLicense: true,
    hasCodeOfConduct: true,
    hasIssueTemplates: true,
  });
  assert.strictEqual(walkable.score, 50);
  assert.strictEqual(walkable.verdict.id, "walkable");

  var welcoming = scoring.computeReadinessScore({
    hasReadme: true,
    hasContributing: true,
    hasLicense: true,
    hasCodeOfConduct: true,
    hasIssueTemplates: true,
    goodFirstIssueCount: 4,
    goodFirstLabelName: "good first issue",
    daysSinceLastPush: 90,
  });
  assert.strictEqual(welcoming.score, 70);
  assert.strictEqual(welcoming.verdict.id, "welcoming");

  var justUnder = scoring.computeReadinessScore({
    hasReadme: true,
    hasContributing: true,
    hasLicense: true,
    hasCodeOfConduct: true,
    hasIssueTemplates: true,
    goodFirstIssueCount: 9,
    goodFirstLabelName: "good first issue",
    daysSinceLastPush: 180,
  });
  assert.strictEqual(justUnder.score, 69);
  assert.strictEqual(justUnder.verdict.id, "walkable");
});

test("rankStarterIssues returns three unassigned starter issues with a why line", function () {
  var now = Date.parse("2026-10-15T00:00:00Z");
  var ranked = scoring.rankStarterIssues([
    {
      number: 9,
      title: "Assigned already",
      comments: 0,
      created_at: "2026-10-14T00:00:00Z",
      labels: [{ name: "good first issue", color: "7057ff" }],
      assignee: { login: "ada" },
      assignees: [{ login: "ada" }],
    },
    {
      number: 8,
      title: "This is a pull request",
      comments: 0,
      created_at: "2026-10-14T00:00:00Z",
      labels: ["good first issue"],
      pull_request: { url: "https://api.github.com/repos/acme/widgets/pulls/8" },
    },
    {
      number: 7,
      title: "Plain bug",
      comments: 0,
      created_at: "2026-10-14T00:00:00Z",
      labels: [{ name: "bug" }],
    },
    {
      number: 3,
      title: "Closed starter",
      state: "closed",
      comments: 0,
      created_at: "2026-10-14T00:00:00Z",
      labels: [{ name: "good first issue" }],
    },
    {
      number: 4,
      title: "Typo in the intro",
      html_url: "https://github.com/acme/widgets/issues/4",
      comments: 0,
      created_at: "2026-10-03T00:00:00Z",
      labels: [{ name: "good first issue", color: "7057ff" }],
      assignee: null,
      assignees: [],
    },
    {
      number: 5,
      title: "Docs gap",
      html_url: "https://github.com/acme/widgets/issues/5",
      comments: 2,
      created_at: "2026-10-01T00:00:00Z",
      labels: [{ name: "help wanted" }],
    },
    {
      number: 5,
      title: "Same docs gap from another label",
      html_url: "https://github.com/acme/widgets/issues/5",
      comments: 2,
      created_at: "2026-10-01T00:00:00Z",
      labels: [{ name: "hacktoberfest" }],
    },
    {
      number: 2,
      title: "Older quiet bugfix",
      comments: 0,
      created_at: "2026-06-01T00:00:00Z",
      labels: [{ name: "good first issue" }],
    },
    {
      number: 1,
      title: "Chatty starter",
      comments: 12,
      created_at: "2026-10-10T00:00:00Z",
      labels: [{ name: "good first issue" }],
    },
  ], now);

  assert.strictEqual(ranked.length, 3);
  assert.deepStrictEqual(ranked.map(function (issue) { return issue.number; }), [4, 2, 5]);
  assert.strictEqual(ranked[0].why, "Unassigned good first issue, no comments yet, opened 12 days ago.");
  assert.strictEqual(ranked[0].title, "Typo in the intro");
  assert.strictEqual(ranked[2].why, "Unassigned help wanted + Hacktoberfest, 2 comments, opened 14 days ago.");
  assert.ok(ranked[2].labels.some(function (label) { return label.name === "hacktoberfest"; }));
  assert.ok(ranked[2].labels.some(function (label) { return label.name === "help wanted"; }));
});

test("rankStarterIssues returns fewer than three when that is all that qualifies", function () {
  assert.deepStrictEqual(scoring.rankStarterIssues(null), []);
  var only = scoring.rankStarterIssues([
    { number: 1, title: "Solo", comments: 0, created_at: "2026-10-01T00:00:00Z", labels: ["help wanted"] },
  ], Date.parse("2026-10-15T00:00:00Z"));
  assert.strictEqual(only.length, 1);
  assert.ok(only[0].why.indexOf("Unassigned help wanted") === 0);
});

if (process.exitCode) {
  console.error("\n" + passed + " passed, some failed");
} else {
  console.log("\n" + passed + " passed");
}
