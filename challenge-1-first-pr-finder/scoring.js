(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.FirstPrScoring = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var WEIGHTS = {
    readme: 10,
    contributing: 12,
    license: 10,
    codeOfConduct: 8,
    issueTemplates: 10,
    starterIssues: 15,
    activity: 15,
    response: 10,
    mergeRatio: 10,
  };

  var MAINTAINER_ROLES = { OWNER: true, MEMBER: true, COLLABORATOR: true };

  function clampCount(value) {
    var n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return 0;
    return Math.floor(n);
  }

  function isSegment(value) {
    if (!/^[A-Za-z0-9_.-]+$/.test(value)) return false;
    if (value === "." || value === "..") return false;
    return true;
  }

  function pair(owner, repo) {
    if (!isSegment(owner) || !isSegment(repo)) return null;
    return { owner: owner, repo: repo };
  }

  function parseRepoInput(raw) {
    if (raw == null) return null;
    var text = String(raw).trim().replace(/\/+$/, "").replace(/\.git$/i, "");
    if (!text) return null;

    var ssh = text.match(/^git@github\.com:([^/\s]+)\/([^/\s]+)$/i);
    if (ssh) return pair(ssh[1], ssh[2]);

    if (/^(https?:\/\/|github\.com\/|www\.github\.com\/)/i.test(text)) {
      try {
        var url = new URL(/^https?:\/\//i.test(text) ? text : "https://" + text);
        var host = url.hostname.toLowerCase().replace(/^www\./, "");
        if (host !== "github.com") return null;
        var parts = url.pathname.split("/").filter(Boolean);
        if (parts.length < 2) return null;
        return pair(parts[0], parts[1]);
      } catch (err) {
        return null;
      }
    }

    var plain = text.split("/").filter(Boolean);
    if (plain.length !== 2) return null;
    return pair(plain[0], plain[1]);
  }

  function classifyLabel(name) {
    var n = String(name || "").trim().toLowerCase();
    if (!n) return null;
    if (/(^|[^a-z0-9])good[\s_-]*first[\s_-]*issues?([^a-z0-9]|$)/.test(n)) return "goodFirst";
    if (/(^|[^a-z0-9])beginner[\s_-]*friendly([^a-z0-9]|$)/.test(n)) return "goodFirst";
    if (/(^|[^a-z0-9])first[\s_-]*timers?[\s_-]*only([^a-z0-9]|$)/.test(n)) return "goodFirst";
    if (/(^|[^a-z0-9])help[\s_-]*wanted([^a-z0-9]|$)/.test(n)) return "helpWanted";
    if (!/accepted|invalid|spam/.test(n)) {
      if (n === "hacktoberfest" || /^hacktoberfest[\s_-]?20\d\d$/.test(n)) return "hacktoberfest";
    }
    return null;
  }

  function groupStarterLabels(labels) {
    var buckets = { goodFirst: [], helpWanted: [], hacktoberfest: [] };
    var list = Array.isArray(labels) ? labels : [];
    for (var i = 0; i < list.length; i++) {
      var entry = list[i];
      var name = typeof entry === "string" ? entry : entry && entry.name;
      var kind = classifyLabel(name);
      if (kind) buckets[kind].push(String(name));
    }
    var prefs = {
      goodFirst: ["good first issue", "good-first-issue"],
      helpWanted: ["help wanted", "help-wanted"],
      hacktoberfest: ["hacktoberfest"],
    };
    function pick(kind) {
      var names = buckets[kind];
      if (!names.length) return null;
      var preferred = prefs[kind];
      for (var p = 0; p < preferred.length; p++) {
        for (var n = 0; n < names.length; n++) {
          if (names[n].toLowerCase() === preferred[p]) return names[n];
        }
      }
      return names[0];
    }
    return {
      goodFirst: pick("goodFirst"),
      helpWanted: pick("helpWanted"),
      hacktoberfest: pick("hacktoberfest"),
    };
  }

  function median(values) {
    if (!Array.isArray(values) || values.length === 0) return null;
    var nums = [];
    for (var i = 0; i < values.length; i++) {
      var value = values[i];
      if (value == null || value === "") continue;
      var n = Number(value);
      if (Number.isFinite(n)) nums.push(n);
    }
    if (!nums.length) return null;
    nums.sort(function (a, b) { return a - b; });
    var mid = Math.floor(nums.length / 2);
    if (nums.length % 2 === 0) return (nums[mid - 1] + nums[mid]) / 2;
    return nums[mid];
  }

  function firstMaintainerResponseHours(issueCreatedAt, comments, authorLogin) {
    if (!Array.isArray(comments) || !comments.length) return null;
    var opened = new Date(issueCreatedAt).getTime();
    if (!Number.isFinite(opened)) return null;
    var ordered = comments.slice().sort(function (a, b) {
      return new Date(a && a.created_at).getTime() - new Date(b && b.created_at).getTime();
    });
    for (var i = 0; i < ordered.length; i++) {
      var comment = ordered[i] || {};
      var user = comment.user || {};
      if (!user.login) continue;
      if (String(user.type || "").toLowerCase() === "bot") continue;
      if (authorLogin && user.login === authorLogin) continue;
      var role = String(comment.author_association || "").toUpperCase();
      if (!MAINTAINER_ROLES[role]) continue;
      var replied = new Date(comment.created_at).getTime();
      if (!Number.isFinite(replied)) continue;
      return Math.max(0, (replied - opened) / 36e5);
    }
    return null;
  }

  function knownFlag(input, key) {
    if (!input.known || typeof input.known !== "object") return true;
    if (!Object.prototype.hasOwnProperty.call(input.known, key)) return true;
    return Boolean(input.known[key]);
  }

  function docRow(id, label, max, present, isKnown, presentText, missingText) {
    if (!isKnown) {
      return {
        id: id,
        label: label,
        points: 0,
        max: max,
        detail: label + " could not be checked, so this signal earns 0 of " + max + ".",
      };
    }
    if (present) {
      return {
        id: id,
        label: label,
        points: max,
        max: max,
        detail: presentText,
      };
    }
    return {
      id: id,
      label: label,
      points: 0,
      max: max,
      detail: missingText,
    };
  }

  function activityPoints(days) {
    if (days <= 7) return 15;
    if (days <= 30) return 12;
    if (days <= 90) return 8;
    if (days <= 180) return 4;
    if (days <= 365) return 2;
    return 0;
  }

  function activityRule(points) {
    if (points >= 15) return "A push within 7 days earns 15 of 15.";
    if (points >= 12) return "A push within 30 days earns 12 of 15.";
    if (points >= 8) return "A push within 90 days earns 8 of 15.";
    if (points >= 4) return "A push within 180 days earns 4 of 15.";
    if (points >= 2) return "A push within a year earns 2 of 15.";
    return "No push in the last year earns 0 of 15.";
  }

  function formatPushAge(days) {
    if (days < 1) return "less than a day ago";
    var whole = Math.floor(days);
    if (whole <= 1) return "1 day ago";
    return whole + " days ago";
  }

  function activityRow(input) {
    var raw = input.daysSinceLastPush;
    if (raw == null || !Number.isFinite(Number(raw))) {
      return {
        id: "activity",
        label: "Recent pushes",
        points: 0,
        max: WEIGHTS.activity,
        detail: "No push timestamp was available, so this signal earns 0 of 15.",
      };
    }
    var days = Number(raw);
    var points = activityPoints(days);
    return {
      id: "activity",
      label: "Recent pushes",
      points: points,
      max: WEIGHTS.activity,
      detail: "Last push was " + formatPushAge(days) + ". " + activityRule(points),
    };
  }

  function formatHours(hours) {
    if (hours < 1) {
      var minutes = Math.max(1, Math.round(hours * 60));
      return minutes === 1 ? "1 minute" : minutes + " minutes";
    }
    if (hours < 36) {
      var rounded = Math.round(hours);
      return rounded === 1 ? "1 hour" : rounded + " hours";
    }
    var days = Math.round(hours / 24);
    return days === 1 ? "1 day" : days + " days";
  }

  function responseRule(points) {
    if (points >= 10) return "A median of 24 hours or less earns 10 of 10.";
    if (points >= 8) return "A median of 3 days or less earns 8 of 10.";
    if (points >= 6) return "A median of 7 days or less earns 6 of 10.";
    if (points >= 4) return "A median of 14 days or less earns 4 of 10.";
    if (points >= 2) return "A median of 30 days or less earns 2 of 10.";
    return "A slower median still earns 1 of 10 for having a response on record.";
  }

  function responsePoints(hours) {
    if (hours <= 24) return 10;
    if (hours <= 72) return 8;
    if (hours <= 168) return 6;
    if (hours <= 336) return 4;
    if (hours <= 720) return 2;
    return 1;
  }

  function responseRow(input) {
    var max = WEIGHTS.response;
    if (input.responseKnown === false) {
      return {
        id: "response",
        label: "Maintainer response",
        points: 0,
        max: max,
        detail: "Maintainer replies could not be loaded, so this signal earns 0 of 10.",
      };
    }
    var hours = input.medianResponseHours;
    var sample = clampCount(input.responseSampleSize);
    var checked = clampCount(input.responseThreadsChecked);
    if (hours == null || !Number.isFinite(Number(hours))) {
      if (checked > 0) {
        return {
          id: "response",
          label: "Maintainer response",
          points: 0,
          max: max,
          detail: "Checked " + checked + " recent " + (checked === 1 ? "thread" : "threads") + " and found no comment from an owner, member, or collaborator in the first page of replies, so this signal earns 0 of 10.",
        };
      }
      return {
        id: "response",
        label: "Maintainer response",
        points: 0,
        max: max,
        detail: "No recent issues or pull requests with comments were available to sample, so this signal earns 0 of 10.",
      };
    }
    var h = Math.max(0, Number(hours));
    var points = responsePoints(h);
    var across = sample > 0
      ? " across " + sample + (sample === 1 ? " thread" : " threads") + " with a maintainer reply"
      : "";
    var detail = "Median first maintainer comment was " + formatHours(h) + across + ". " + responseRule(points);
    var missed = checked - sample;
    if (missed > 0) {
      detail += " " + missed + " other sampled " + (missed === 1 ? "thread" : "threads") + " had no maintainer comment in the first page of replies.";
    }
    return {
      id: "response",
      label: "Maintainer response",
      points: points,
      max: max,
      detail: detail,
    };
  }

  function formatPercent(ratio) {
    var pct = ratio * 100;
    if (Math.abs(pct - Math.round(pct)) < 1e-9) return Math.round(pct) + "%";
    return pct.toFixed(1) + "%";
  }

  function mergePoints(ratio) {
    if (ratio >= 0.8) return 10;
    if (ratio >= 0.6) return 8;
    if (ratio >= 0.4) return 6;
    if (ratio >= 0.2) return 3;
    if (ratio > 0) return 1;
    return 0;
  }

  function mergeRule(points) {
    if (points >= 10) return "A merge ratio of at least 80% earns 10 of 10.";
    if (points >= 8) return "A merge ratio of at least 60% earns 8 of 10.";
    if (points >= 6) return "A merge ratio of at least 40% earns 6 of 10.";
    if (points >= 3) return "A merge ratio of at least 20% earns 3 of 10.";
    if (points >= 1) return "A few merges in the sample earn 1 of 10.";
    return "No merges in the sample earn 0 of 10.";
  }

  function mergeRow(input) {
    var max = WEIGHTS.mergeRatio;
    if (input.mergeSampleKnown === false) {
      return {
        id: "mergeRatio",
        label: "Pull request merge ratio",
        points: 0,
        max: max,
        detail: "Closed pull requests could not be loaded, so this signal earns 0 of 10.",
      };
    }
    var sampleRaw = input.closedPullRequestSample;
    if (sampleRaw == null || !Number.isFinite(Number(sampleRaw))) {
      return {
        id: "mergeRatio",
        label: "Pull request merge ratio",
        points: 0,
        max: max,
        detail: "No closed pull requests were in the sample, so this signal earns 0 of 10.",
      };
    }
    var sample = Math.floor(Number(sampleRaw));
    if (sample <= 0) {
      return {
        id: "mergeRatio",
        label: "Pull request merge ratio",
        points: 0,
        max: max,
        detail: "No closed pull requests were in the sample, so this signal earns 0 of 10.",
      };
    }
    var merged = Math.max(0, Math.min(sample, clampCount(input.mergedPullRequests)));
    var ratio = merged / sample;
    var points = mergePoints(ratio);
    var head = sample === 1
      ? merged + " of 1 recently updated closed pull request was merged (" + formatPercent(ratio) + ")."
      : merged + " of " + sample + " recently updated closed pull requests were merged (" + formatPercent(ratio) + ").";
    return {
      id: "mergeRatio",
      label: "Pull request merge ratio",
      points: points,
      max: max,
      detail: head + " " + mergeRule(points),
    };
  }

  function starterPoints(total) {
    if (total <= 0) return 0;
    if (total === 1) return 4;
    if (total <= 3) return 8;
    if (total <= 8) return 12;
    return 15;
  }

  function starterRule(points) {
    if (points >= 15) return "A combined total of 9 or more earns 15 of 15.";
    if (points >= 12) return "A combined 4 to 8 earns 12 of 15.";
    if (points >= 8) return "A combined 2 to 3 earns 8 of 15.";
    if (points >= 4) return "A combined 1 earns 4 of 15.";
    return "No open issues with those labels, so this signal earns 0 of 15.";
  }

  function readBucket(input, spec) {
    var name = input[spec.nameKey] ? String(input[spec.nameKey]) : "";
    var raw = input[spec.countKey];
    if (!name) return { text: spec.absent, count: 0, state: "absent" };
    if (raw == null || !Number.isFinite(Number(raw))) {
      return { text: spec.unavailable, count: 0, state: "unavailable" };
    }
    var count = clampCount(raw);
    return {
      text: 'Label "' + name + '": ' + count + " open " + (count === 1 ? "issue" : "issues") + ".",
      count: count,
      state: "known",
    };
  }

  function starterRow(input) {
    var max = WEIGHTS.starterIssues;
    if (input.starterCountsKnown === false) {
      return {
        id: "starterIssues",
        label: "Starter issues",
        points: 0,
        max: max,
        detail: "Starter-issue labels could not be counted, so this signal earns 0 of 15.",
      };
    }
    var specs = [
      {
        countKey: "goodFirstIssueCount",
        nameKey: "goodFirstLabelName",
        absent: "No good first issue label on this repo.",
        unavailable: "Good first issue count unavailable.",
      },
      {
        countKey: "helpWantedCount",
        nameKey: "helpWantedLabelName",
        absent: "No help wanted label on this repo.",
        unavailable: "Help wanted count unavailable.",
      },
      {
        countKey: "hacktoberfestCount",
        nameKey: "hacktoberfestLabelName",
        absent: "No hacktoberfest label on this repo.",
        unavailable: "Hacktoberfest count unavailable.",
      },
    ];
    var parts = [];
    var total = 0;
    var positive = 0;
    var unavailable = 0;
    for (var i = 0; i < specs.length; i++) {
      var bucket = readBucket(input, specs[i]);
      parts.push(bucket.text);
      total += bucket.count;
      if (bucket.count > 0) positive += 1;
      if (bucket.state === "unavailable") unavailable += 1;
    }
    var points = starterPoints(total);
    var detail = parts.join(" ") + " " + starterRule(points);
    if (positive >= 2) {
      detail += " Issues with more than one of these labels are counted in each tally.";
    }
    detail += " Pull requests are not included.";
    if (input.starterCountsTruncated) {
      detail += " A label with more open items than the newest 100 is counted from that page only, so the tally may be low.";
    }
    if (unavailable > 0) {
      detail += " " + unavailable + " label " + (unavailable === 1 ? "count" : "counts") + " unavailable, so this tally may be low.";
    }
    return {
      id: "starterIssues",
      label: "Starter issues",
      points: points,
      max: max,
      detail: detail,
    };
  }

  function verdictFor(score) {
    if (score >= 85) {
      return {
        id: "ready",
        title: "Ready for a first contribution",
        blurb: "Docs, starter issues, and maintainer signals look solid.",
      };
    }
    if (score >= 70) {
      return {
        id: "welcoming",
        title: "Welcoming, with a few gaps",
        blurb: "A newcomer can start here. Check the missing points before opening a pull request.",
      };
    }
    if (score >= 50) {
      return {
        id: "walkable",
        title: "Possible, but you will do some digging",
        blurb: "Some onboarding is in place. Read the gaps so the first pull request fits.",
      };
    }
    if (score >= 30) {
      return {
        id: "thin",
        title: "Thin onboarding",
        blurb: "You can still contribute, but expect to ask where work belongs.",
      };
    }
    return {
      id: "hard",
      title: "Hard for a first-time contributor",
      blurb: "Little of the usual onboarding is present yet.",
    };
  }

  function computeReadinessScore(input) {
    var src = input && typeof input === "object" ? input : {};
    var breakdown = [
      docRow(
        "readme",
        "README",
        WEIGHTS.readme,
        Boolean(src.hasReadme),
        knownFlag(src, "readme"),
        "README is present. That earns 10 of 10.",
        "README was not found. A README is the front door for new contributors. It is worth 10 points."
      ),
      docRow(
        "contributing",
        "CONTRIBUTING",
        WEIGHTS.contributing,
        Boolean(src.hasContributing),
        knownFlag(src, "contributing"),
        "CONTRIBUTING is present. That earns 12 of 12.",
        "CONTRIBUTING was not found. A contributing guide tells people how to open a pull request. It is worth 12 points."
      ),
      docRow(
        "license",
        "LICENSE",
        WEIGHTS.license,
        Boolean(src.hasLicense),
        knownFlag(src, "license"),
        "LICENSE is present. That earns 10 of 10.",
        "LICENSE was not found. A license tells contributors whether they can use and change the code. It is worth 10 points."
      ),
      docRow(
        "codeOfConduct",
        "CODE_OF_CONDUCT",
        WEIGHTS.codeOfConduct,
        Boolean(src.hasCodeOfConduct),
        knownFlag(src, "codeOfConduct"),
        "CODE_OF_CONDUCT is present. That earns 8 of 8.",
        "CODE_OF_CONDUCT was not found. A code of conduct sets expectations for how people treat each other. It is worth 8 points."
      ),
      docRow(
        "issueTemplates",
        "Issue templates",
        WEIGHTS.issueTemplates,
        Boolean(src.hasIssueTemplates),
        knownFlag(src, "issueTemplates"),
        "Issue templates are present. That earns 10 of 10.",
        "Issue templates were not found. Templates steer newcomers toward useful reports. They are worth 10 points."
      ),
      starterRow(src),
      activityRow(src),
      responseRow(src),
      mergeRow(src),
    ];
    var score = 0;
    for (var i = 0; i < breakdown.length; i++) score += breakdown[i].points;
    score = Math.max(0, Math.min(100, score));
    return {
      score: score,
      verdict: verdictFor(score),
      breakdown: breakdown,
    };
  }

  function labelName(label) {
    if (typeof label === "string") return label;
    if (label && typeof label.name === "string") return label.name;
    return "";
  }

  function isAssigned(issue) {
    if (!issue) return false;
    if (issue.assignee) return true;
    return Array.isArray(issue.assignees) && issue.assignees.length > 0;
  }

  function mergeIssueRecords(issues) {
    var map = new Map();
    var order = [];
    for (var i = 0; i < issues.length; i++) {
      var issue = issues[i];
      if (!issue || !Number.isFinite(Number(issue.number))) continue;
      var number = Number(issue.number);
      var existing = map.get(number);
      if (!existing) {
        map.set(number, {
          number: number,
          title: issue.title,
          html_url: issue.html_url || "",
          comments: issue.comments,
          created_at: issue.created_at,
          state: issue.state,
          assignee: issue.assignee,
          assignees: issue.assignees,
          pull_request: issue.pull_request,
          labels: Array.isArray(issue.labels) ? issue.labels.slice() : [],
        });
        order.push(number);
        continue;
      }
      var seen = {};
      for (var s = 0; s < existing.labels.length; s++) seen[labelName(existing.labels[s])] = true;
      var incoming = Array.isArray(issue.labels) ? issue.labels : [];
      for (var n = 0; n < incoming.length; n++) {
        var name = labelName(incoming[n]);
        if (name && !seen[name]) {
          existing.labels.push(incoming[n]);
          seen[name] = true;
        }
      }
      var comments = Number(issue.comments);
      if (Number.isFinite(comments) && comments > (Number(existing.comments) || 0)) {
        existing.comments = comments;
      }
      if (!existing.html_url && issue.html_url) existing.html_url = issue.html_url;
      if (issue.assignee) existing.assignee = issue.assignee;
      if (Array.isArray(issue.assignees) && issue.assignees.length) existing.assignees = issue.assignees;
      if (issue.pull_request) existing.pull_request = issue.pull_request;
    }
    return order.map(function (number) { return map.get(number); });
  }

  function ageText(ageDays) {
    if (!Number.isFinite(ageDays)) return "age unknown";
    if (ageDays < 1) return "opened today";
    if (ageDays < 2) return "opened yesterday";
    var whole = Math.floor(ageDays);
    return "opened " + whole + " days ago";
  }

  function whyLine(classes, comments, ageDays) {
    var labels = [];
    if (classes.goodFirst) labels.push("good first issue");
    if (classes.helpWanted) labels.push("help wanted");
    if (classes.hacktoberfest) labels.push("Hacktoberfest");
    var labelText = labels.length ? labels.join(" + ") : "starter issue";
    var commentText = comments === 0 ? "no comments yet" : comments === 1 ? "1 comment" : comments + " comments";
    return "Unassigned " + labelText + ", " + commentText + ", " + ageText(ageDays) + ".";
  }

  function rankStarterIssues(issues, now) {
    var nowMs = now instanceof Date ? now.getTime() : Number(now);
    if (!Number.isFinite(nowMs)) nowMs = Date.now();
    var merged = mergeIssueRecords(Array.isArray(issues) ? issues : []);
    var ranked = [];
    for (var i = 0; i < merged.length; i++) {
      var issue = merged[i];
      if (issue.pull_request) continue;
      if (issue.state && issue.state !== "open") continue;
      if (isAssigned(issue)) continue;
      var classes = { goodFirst: false, helpWanted: false, hacktoberfest: false };
      var labels = [];
      var seen = {};
      var sourceLabels = Array.isArray(issue.labels) ? issue.labels : [];
      for (var l = 0; l < sourceLabels.length; l++) {
        var name = labelName(sourceLabels[l]);
        if (!name || seen[name]) continue;
        seen[name] = true;
        var color = sourceLabels[l] && sourceLabels[l].color ? String(sourceLabels[l].color) : "";
        labels.push({ name: name, color: color });
        var kind = classifyLabel(name);
        if (kind) classes[kind] = true;
      }
      if (!classes.goodFirst && !classes.helpWanted && !classes.hacktoberfest) continue;
      var comments = clampCount(issue.comments);
      var created = new Date(issue.created_at).getTime();
      var ageDays = Number.isFinite(created) ? (nowMs - created) / 86400000 : NaN;
      var rank = 0;
      if (classes.goodFirst) rank += 50;
      if (classes.helpWanted) rank += 22;
      if (classes.hacktoberfest) rank += 18;
      if (comments === 0) rank += 24;
      else if (comments <= 2) rank += 16;
      else if (comments <= 5) rank += 8;
      else if (comments <= 10) rank += 2;
      else rank -= 6;
      if (Number.isFinite(ageDays)) {
        if (ageDays <= 14) rank += 16;
        else if (ageDays <= 45) rank += 12;
        else if (ageDays <= 120) rank += 6;
        else if (ageDays > 365) rank -= 8;
      }
      var title = String(issue.title || "").trim() || "(untitled)";
      ranked.push({
        number: issue.number,
        title: title,
        html_url: issue.html_url || "",
        comments: comments,
        created_at: issue.created_at || "",
        labels: labels.slice(0, 6),
        why: whyLine(classes, comments, ageDays),
        rank: rank,
        ageDays: Number.isFinite(ageDays) ? ageDays : Infinity,
      });
    }
    ranked.sort(function (a, b) {
      if (b.rank !== a.rank) return b.rank - a.rank;
      if (a.comments !== b.comments) return a.comments - b.comments;
      if (a.ageDays !== b.ageDays) return a.ageDays - b.ageDays;
      return a.number - b.number;
    });
    return ranked.slice(0, 3).map(function (issue) {
      return {
        number: issue.number,
        title: issue.title,
        html_url: issue.html_url,
        comments: issue.comments,
        created_at: issue.created_at,
        labels: issue.labels,
        why: issue.why,
        rank: issue.rank,
      };
    });
  }

  return {
    WEIGHTS: WEIGHTS,
    parseRepoInput: parseRepoInput,
    classifyLabel: classifyLabel,
    groupStarterLabels: groupStarterLabels,
    median: median,
    firstMaintainerResponseHours: firstMaintainerResponseHours,
    computeReadinessScore: computeReadinessScore,
    rankStarterIssues: rankStarterIssues,
  };
});
