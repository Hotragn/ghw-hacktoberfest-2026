(function () {
  "use strict";

  var TOKEN_KEY = "first-pr-finder:token";
  var THEME_KEY = "first-pr-finder:theme";
  var scoring = window.FirstPrScoring;

  var form = document.getElementById("finder-form");
  var repoInput = document.getElementById("repo");
  var tokenInput = document.getElementById("token");
  var submitBtn = document.getElementById("submit-btn");
  var formError = document.getElementById("form-error");
  var tokenStatus = document.getElementById("token-status");
  var statusEl = document.getElementById("status");
  var resultEl = document.getElementById("result");
  var themeButton = document.getElementById("theme-toggle");
  var clearTokenBtn = document.getElementById("clear-token");
  var exampleButtons = Array.prototype.slice.call(document.querySelectorAll("[data-repo]"));

  var runId = 0;
  var activeController = null;

  function h(tag, props, children) {
    var node = document.createElement(tag);
    var attrs = props || {};
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value == null || value === false) return;
      if (key === "class") node.className = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    });
    (children || []).forEach(function (child) {
      if (child == null || child === false) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function readStorage(key) {
    try { return localStorage.getItem(key) || ""; } catch (err) { return ""; }
  }

  function writeStorage(key, value) {
    try {
      if (value) localStorage.setItem(key, value);
      else localStorage.removeItem(key);
    } catch (err) { /* private mode */ }
  }

  function normalizeToken(value) {
    return String(value || "").trim().replace(/^(bearer|token)\s+/i, "");
  }

  function setTokenStatus() {
    tokenStatus.textContent = readStorage(TOKEN_KEY)
      ? "A token is saved in this browser."
      : "No token saved. Unauthenticated use allows about 60 requests an hour.";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
    var dark = theme === "dark";
    themeButton.textContent = dark ? "Theme: dark" : "Theme: light";
    themeButton.setAttribute("aria-pressed", dark ? "true" : "false");
    themeButton.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }

  function initTheme() {
    applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
    themeButton.addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      writeStorage(THEME_KEY, next);
      applyTheme(next);
    });
    var media = window.matchMedia("(prefers-color-scheme: dark)");
    if (media.addEventListener) {
      media.addEventListener("change", function (event) {
        if (!readStorage(THEME_KEY)) applyTheme(event.matches ? "dark" : "light");
      });
    }
  }

  function setFormError(message) {
    formError.hidden = !message;
    formError.textContent = message || "";
  }

  function setStatus(message) {
    statusEl.hidden = !message;
    statusEl.textContent = message || "";
  }

  function setBusy(busy) {
    submitBtn.disabled = busy;
    submitBtn.textContent = busy ? "Scoring…" : "Score this repo";
    exampleButtons.forEach(function (button) { button.disabled = busy; });
    repoInput.disabled = busy;
  }

  function setRepoParam(fullName) {
    var url = new URL(window.location.href);
    url.search = "?repo=" + fullName;
    url.hash = "";
    history.replaceState(null, "", url);
  }

  function waitPhrase(resetSeconds) {
    var ms = Number(resetSeconds) * 1000;
    if (!Number.isFinite(ms)) return "until the limit resets";
    var delta = ms - Date.now();
    if (delta <= 0) return "a moment";
    var mins = Math.ceil(delta / 60000);
    if (mins < 90) return "about " + mins + " minute" + (mins === 1 ? "" : "s");
    return "until " + new Date(ms).toLocaleString();
  }

  function resetPhrase(resetSeconds) {
    var phrase = waitPhrase(resetSeconds);
    if (phrase.indexOf("until") === 0 || phrase === "a moment") return phrase;
    return "in " + phrase;
  }

  function isAbort(err) {
    return err && err.name === "AbortError";
  }

  function readLimit(res) {
    return {
      remaining: res.headers.get("X-RateLimit-Remaining"),
      reset: res.headers.get("X-RateLimit-Reset"),
      resource: res.headers.get("X-RateLimit-Resource"),
    };
  }

  async function gh(path, options) {
    var opts = options || {};
    var headers = {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    };
    if (opts.token) headers.Authorization = "Bearer " + opts.token;
    var res;
    try {
      res = await fetch("https://api.github.com" + path, { headers: headers, signal: opts.signal });
    } catch (err) {
      if (isAbort(err)) throw err;
      var network = new Error("The browser could not reach api.github.com.");
      network.code = "NETWORK";
      throw network;
    }
    var limit = readLimit(res);
    var text = await res.text();
    var body = null;
    if (text) {
      try { body = JSON.parse(text); }
      catch (err) { body = { message: text.slice(0, 180) }; }
    }
    if (res.ok) return { body: body, limit: limit, link: res.headers.get("Link") };
    var message = body && body.message ? body.message : "GitHub returned " + res.status;
    var error = new Error(message);
    error.limit = limit;
    error.status = res.status;
    if (res.status === 404) error.code = "NOT_FOUND";
    else if (res.status === 401 || /bad credentials/i.test(message)) error.code = "BAD_TOKEN";
    else if (res.status === 403 || res.status === 429) {
      var limited = limit.remaining === "0" || res.status === 429 || /rate limit/i.test(message);
      error.code = limited ? "RATE_LIMIT" : "FORBIDDEN";
    } else error.code = "HTTP";
    throw error;
  }

  function nextPath(link) {
    if (!link) return null;
    var match = link.match(/<([^>]+)>;\s*rel="next"/);
    if (!match) return null;
    return match[1].replace(/^https:\/\/api\.github\.com/i, "");
  }

  async function fetchLabels(owner, repo, token, signal) {
    var labels = [];
    var path = "/repos/" + owner + "/" + repo + "/labels?per_page=100";
    var limit = null;
    for (var page = 0; page < 2; page++) {
      var res = await gh(path, { token: token, signal: signal });
      limit = res.limit;
      if (Array.isArray(res.body)) labels = labels.concat(res.body);
      var next = nextPath(res.link);
      if (!next) return { labels: labels, limit: limit, truncated: false };
      path = next;
    }
    return { labels: labels, limit: limit, truncated: true };
  }

  function scanEntries(entries) {
    var list = Array.isArray(entries) ? entries : [];
    function has(re) {
      return list.some(function (entry) { return re.test(String(entry && entry.name || "")); });
    }
    var templateDir = list.some(function (entry) {
      return entry && entry.type === "dir" && /^issue_template$/i.test(entry.name || "");
    });
    return {
      readme: has(/^readme(\..+)?$/i),
      contributing: has(/^contributing(\..+)?$/i),
      license: has(/^(license|licence|copying|unlicense)(\..+)?$/i),
      coc: has(/^code[-_]of[-_]conduct(\..+)?$/i),
      issue: has(/^issue_template(\..+)?$/i) || templateDir,
    };
  }

  async function readDocsFromContents(owner, repo, token, signal) {
    var rootRes = await gh("/repos/" + owner + "/" + repo + "/contents/", { token: token, signal: signal });
    var root = scanEntries(rootRes.body);
    var github = { contributing: false, coc: false, issue: false };
    try {
      var githubRes = await gh("/repos/" + owner + "/" + repo + "/contents/.github", { token: token, signal: signal });
      github = scanEntries(githubRes.body);
    } catch (err) {
      if (isAbort(err) || (err && (err.code === "RATE_LIMIT" || err.code === "BAD_TOKEN"))) throw err;
    }
    return {
      hasReadme: root.readme,
      hasContributing: root.contributing || github.contributing,
      hasLicense: root.license,
      hasCodeOfConduct: root.coc || github.coc,
      hasIssueTemplates: root.issue || github.issue,
      limit: rootRes.limit,
    };
  }

  function docsFromProfile(profile) {
    var files = profile && profile.files;
    if (!files) return null;
    return {
      hasReadme: Boolean(files.readme),
      hasContributing: Boolean(files.contributing),
      hasLicense: Boolean(files.license),
      hasCodeOfConduct: Boolean(files.code_of_conduct || files.code_of_conduct_file),
      hasIssueTemplates: Boolean(files.issue_template),
    };
  }

  async function listByLabel(owner, repo, label, token, signal) {
    var path = "/repos/" + owner + "/" + repo + "/issues?state=open&sort=created&direction=desc&per_page=100&labels=" + encodeURIComponent(label);
    var res = await gh(path, { token: token, signal: signal });
    var body = Array.isArray(res.body) ? res.body : [];
    var issuesOnly = body.filter(function (item) { return item && !item.pull_request; });
    return {
      total: issuesOnly.length,
      truncated: Boolean(nextPath(res.link)),
      items: issuesOnly,
      limit: res.limit,
    };
  }

  function pickResponseSample(issues, pulls) {
    var issueThreads = [];
    var pullThreads = [];
    (Array.isArray(issues) ? issues : []).forEach(function (item) {
      if (!item || !item.number || Number(item.comments) <= 0) return;
      if (item.pull_request) pullThreads.push(item);
      else issueThreads.push(item);
    });
    (Array.isArray(pulls) ? pulls : []).forEach(function (item) {
      if (!item || !item.number || item.comments === 0) return;
      pullThreads.push(item);
    });
    var chosen = [];
    var seen = {};
    function add(item) {
      if (!item || chosen.length >= 5 || seen[item.number]) return;
      seen[item.number] = true;
      chosen.push({
        number: item.number,
        created_at: item.created_at,
        userLogin: item.user && item.user.login,
      });
    }
    issueThreads.slice(0, 3).forEach(add);
    pullThreads.slice(0, 2).forEach(add);
    issueThreads.forEach(add);
    pullThreads.forEach(add);
    return chosen;
  }

  function daysSince(iso) {
    var t = new Date(iso).getTime();
    if (!Number.isFinite(t)) return null;
    return (Date.now() - t) / 86400000;
  }

  function trackCore(limits, limit) {
    if (!limit || (limit.resource && limit.resource !== "core")) return;
    limits.push(limit);
  }

  function lowestCore(limits) {
    var best = null;
    limits.forEach(function (limit) {
      var n = Number(limit && limit.remaining);
      if (!Number.isFinite(n)) return;
      if (!best || n < Number(best.remaining)) best = limit;
    });
    return best;
  }

  async function analyze(owner, repo, token, signal, onStatus) {
    var warnings = [];
    var limits = [];
    var rateLimited = false;

    function note(err, label) {
      if (!err) return;
      if (isAbort(err)) throw err;
      if (err.code === "RATE_LIMIT") {
        rateLimited = true;
        trackCore(limits, err.limit);
        return;
      }
      if (err.code === "NOT_FOUND") return;
      var message = String(err.message || "request failed").replace(/\s+/g, " ").slice(0, 140);
      warnings.push(label + ": " + message);
    }

    onStatus("Reading the repository");
    var repoRes = await gh("/repos/" + owner + "/" + repo, { token: token, signal: signal });
    trackCore(limits, repoRes.limit);
    var repoBody = repoRes.body || {};

    onStatus("Checking docs, labels, and recent work");
    var settled = await Promise.allSettled([
      gh("/repos/" + owner + "/" + repo + "/community/profile", { token: token, signal: signal }),
      fetchLabels(owner, repo, token, signal),
      gh("/repos/" + owner + "/" + repo + "/issues?state=all&sort=created&direction=desc&per_page=30", { token: token, signal: signal }),
      gh("/repos/" + owner + "/" + repo + "/pulls?state=all&sort=created&direction=desc&per_page=10", { token: token, signal: signal }),
      gh("/repos/" + owner + "/" + repo + "/pulls?state=closed&sort=updated&direction=desc&per_page=30", { token: token, signal: signal }),
    ]);

    var docs = null;
    var docsKnown = false;
    if (settled[0].status === "fulfilled") {
      trackCore(limits, settled[0].value.limit);
      docs = docsFromProfile(settled[0].value.body);
      docsKnown = Boolean(docs);
    } else {
      note(settled[0].reason, "Community profile");
    }
    if (docsKnown && docs && !docs.hasIssueTemplates) {
      try {
        var templateRes = await gh("/repos/" + owner + "/" + repo + "/contents/.github/ISSUE_TEMPLATE", { token: token, signal: signal });
        trackCore(limits, templateRes.limit);
        var templateBody = templateRes.body;
        var templateFiles = Array.isArray(templateBody) ? templateBody.length > 0 : Boolean(templateBody && templateBody.type);
        if (templateFiles) docs.hasIssueTemplates = true;
      } catch (err) {
        if (isAbort(err)) throw err;
        if (err && err.code !== "NOT_FOUND") note(err, "Issue templates");
      }
    }
    if (!docsKnown && !(settled[0].status === "rejected" && settled[0].reason && settled[0].reason.code === "RATE_LIMIT")) {
      try {
        var fromContents = await readDocsFromContents(owner, repo, token, signal);
        docs = fromContents;
        docsKnown = true;
        trackCore(limits, fromContents.limit);
      } catch (err) {
        note(err, "Repository files");
      }
    }

    var labelsLoaded = settled[1].status === "fulfilled";
    var grouped;
    if (labelsLoaded) {
      trackCore(limits, settled[1].value.limit);
      grouped = scoring.groupStarterLabels(settled[1].value.labels);
      if (settled[1].value.truncated) warnings.push("Only the first 200 labels were checked.");
    } else {
      note(settled[1].reason, "Labels");
      grouped = {
        goodFirst: "good first issue",
        helpWanted: "help wanted",
        hacktoberfest: "hacktoberfest",
      };
      warnings.push("Could not list labels, so starter counts use the standard names.");
    }

    var issueBody = [];
    var pullBody = [];
    var issuesOk = settled[2].status === "fulfilled";
    var pullsOk = settled[3].status === "fulfilled";
    if (issuesOk) {
      trackCore(limits, settled[2].value.limit);
      issueBody = Array.isArray(settled[2].value.body) ? settled[2].value.body : [];
    } else note(settled[2].reason, "Recent issues");
    if (pullsOk) {
      trackCore(limits, settled[3].value.limit);
      pullBody = Array.isArray(settled[3].value.body) ? settled[3].value.body : [];
    } else note(settled[3].reason, "Recent pull requests");

    var merge = { known: false, merged: 0, sample: 0 };
    if (settled[4].status === "fulfilled") {
      trackCore(limits, settled[4].value.limit);
      var closed = Array.isArray(settled[4].value.body) ? settled[4].value.body : [];
      merge.known = true;
      merge.sample = closed.length;
      merge.merged = closed.filter(function (pull) { return pull && pull.merged_at; }).length;
    } else note(settled[4].reason, "Closed pull requests");

    onStatus("Sampling replies and starter issues");
    var categories = ["goodFirst", "helpWanted", "hacktoberfest"];
    var starter = { known: true };
    categories.forEach(function (key) {
      starter[key] = { name: grouped[key], count: grouped[key] ? null : 0 };
    });
    var issueItems = [];
    var labelJobs = categories.filter(function (key) { return grouped[key]; });
    var labelResults = await Promise.allSettled(labelJobs.map(function (key) {
      return listByLabel(owner, repo, grouped[key], token, signal);
    }));
    var labelFailures = 0;
    var starterCountsTruncated = false;
    labelResults.forEach(function (result, index) {
      var key = labelJobs[index];
      if (result.status === "fulfilled") {
        var total = result.value.total;
        starter[key].count = Number.isFinite(total) ? total : null;
        if (result.value.truncated) starterCountsTruncated = true;
        issueItems = issueItems.concat(result.value.items);
        trackCore(limits, result.value.limit);
      } else if (result.reason && result.reason.code === "NOT_FOUND") {
        starter[key].count = 0;
      } else {
        labelFailures += 1;
        note(result.reason, "Starter issues");
      }
    });
    if (!labelsLoaded && labelJobs.length && labelFailures === labelJobs.length) starter.known = false;

    var ranked = scoring.rankStarterIssues(issueItems, Date.now());

    var samples = issuesOk || pullsOk ? pickResponseSample(issueBody, pullBody) : [];
    var response = { medianHours: null, hit: 0, checked: 0, known: issuesOk || pullsOk };
    if (samples.length) {
      var commentResults = await Promise.allSettled(samples.map(function (sample) {
        return gh(
          "/repos/" + owner + "/" + repo + "/issues/" + sample.number + "/comments?per_page=30&page=1",
          { token: token, signal: signal }
        );
      }));
      var hours = [];
      var failures = 0;
      commentResults.forEach(function (result, index) {
        if (result.status !== "fulfilled") {
          failures += 1;
          note(result.reason, "Maintainer replies");
          return;
        }
        trackCore(limits, result.value.limit);
        response.checked += 1;
        var elapsed = scoring.firstMaintainerResponseHours(
          samples[index].created_at,
          Array.isArray(result.value.body) ? result.value.body : [],
          samples[index].userLogin
        );
        if (elapsed != null) hours.push(elapsed);
      });
      if (response.checked === 0 && failures === samples.length) response.known = false;
      else {
        response.hit = hours.length;
        response.medianHours = scoring.median(hours);
      }
      if (failures && response.checked) {
        warnings.push(failures + " maintainer-reply lookup" + (failures === 1 ? "" : "s") + " failed.");
      }
    }

    var seen = {};
    warnings = warnings.filter(function (warning) {
      if (seen[warning]) return false;
      seen[warning] = true;
      return true;
    });

    var signals = {
      hasReadme: Boolean(docs && docs.hasReadme),
      hasContributing: Boolean(docs && docs.hasContributing),
      hasLicense: Boolean((docs && docs.hasLicense) || repoBody.license),
      hasCodeOfConduct: Boolean(docs && docs.hasCodeOfConduct),
      hasIssueTemplates: Boolean(docs && docs.hasIssueTemplates),
      known: {
        readme: docsKnown,
        contributing: docsKnown,
        license: docsKnown || Boolean(repoBody.license),
        codeOfConduct: docsKnown,
        issueTemplates: docsKnown,
      },
      goodFirstIssueCount: starter.goodFirst.count,
      goodFirstLabelName: starter.goodFirst.name,
      helpWantedCount: starter.helpWanted.count,
      helpWantedLabelName: starter.helpWanted.name,
      hacktoberfestCount: starter.hacktoberfest.count,
      hacktoberfestLabelName: starter.hacktoberfest.name,
      starterCountsKnown: starter.known,
      starterCountsTruncated: starterCountsTruncated,
      daysSinceLastPush: daysSince(repoBody.pushed_at),
      medianResponseHours: response.medianHours,
      responseSampleSize: response.hit,
      responseThreadsChecked: response.checked,
      responseKnown: response.known,
      mergedPullRequests: merge.merged,
      closedPullRequestSample: merge.known ? merge.sample : null,
      mergeSampleKnown: merge.known,
    };

    return {
      repo: {
        fullName: repoBody.full_name || (owner + "/" + repo),
        description: repoBody.description || "",
        stars: repoBody.stargazers_count,
        language: repoBody.language || "",
        license: repoBody.license && repoBody.license.spdx_id && repoBody.license.spdx_id !== "NOASSERTION"
          ? repoBody.license.spdx_id
          : "",
        htmlUrl: safeGithubUrl(repoBody.html_url, "https://github.com/" + owner + "/" + repo),
        pushedAt: repoBody.pushed_at || "",
      },
      score: scoring.computeReadinessScore(signals),
      issues: ranked,
      warnings: warnings,
      rateLimited: rateLimited,
      limit: lowestCore(limits),
      owner: owner,
      repoName: repo,
    };
  }

  function safeGithubUrl(candidate, fallback) {
    try {
      var url = new URL(candidate || fallback);
      var host = url.hostname.toLowerCase().replace(/^www\./, "");
      if (url.protocol === "https:" && host === "github.com") return url.href;
    } catch (err) { /* use fallback */ }
    return fallback;
  }

  function issueUrl(owner, repo, issue) {
    var fallback = "https://github.com/" + owner + "/" + repo + "/issues/" + issue.number;
    return safeGithubUrl(issue.html_url, fallback);
  }

  function shortAge(iso) {
    var days = daysSince(iso);
    if (days == null) return "push time unknown";
    if (days < 1) return "pushed today";
    var whole = Math.floor(days);
    if (whole <= 1) return "pushed 1 day ago";
    return "pushed " + whole + " days ago";
  }

  function formatStars(value) {
    var n = Number(value);
    if (!Number.isFinite(n)) return "";
    return n.toLocaleString("en-US") + (n === 1 ? " star" : " stars");
  }

  function labelPill(label) {
    var li = h("li", {}, [label.name]);
    var hex = String(label.color || "").replace(/^#/, "");
    if (/^[0-9a-fA-F]{6}$/.test(hex)) {
      var r = parseInt(hex.slice(0, 2), 16);
      var g = parseInt(hex.slice(2, 4), 16);
      var b = parseInt(hex.slice(4, 6), 16);
      var y = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
      li.style.background = "#" + hex;
      li.style.color = y > 0.62 ? "#24160c" : "#f7f4ee";
      li.style.borderColor = "transparent";
    }
    return li;
  }

  function scoreRing(score, tone) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 120 120");
    svg.setAttribute("class", "ring");
    svg.setAttribute("aria-hidden", "true");
    var track = document.createElementNS(ns, "circle");
    track.setAttribute("cx", "60");
    track.setAttribute("cy", "60");
    track.setAttribute("r", "52");
    track.setAttribute("class", "ring-track");
    var value = document.createElementNS(ns, "circle");
    value.setAttribute("cx", "60");
    value.setAttribute("cy", "60");
    value.setAttribute("r", "52");
    value.setAttribute("class", "ring-value tone-" + tone);
    var circumference = 2 * Math.PI * 52;
    value.setAttribute("stroke-dasharray", String(circumference));
    value.setAttribute("stroke-dashoffset", String(circumference));
    svg.appendChild(track);
    svg.appendChild(value);
    requestAnimationFrame(function () {
      value.setAttribute("stroke-dashoffset", String(circumference * (1 - score / 100)));
    });
    return svg;
  }

  function renderLoading() {
    resultEl.replaceChildren(h("section", { class: "panel loading-card" }, [
      h("h2", {}, ["Reading public signals"]),
      h("div", { class: "skeleton wide" }),
      h("div", { class: "skeleton mid" }),
      h("div", { class: "skeleton" }),
    ]));
  }

  function renderError(err, owner, repo) {
    var copy = errorCopy(err, owner, repo);
    setStatus(copy.title + ". " + copy.body);
    resultEl.replaceChildren(h("section", { class: "panel error-card" }, [
      h("p", { class: "eyebrow" }, ["Could not score"]),
      h("h2", {}, [copy.title]),
      h("p", {}, [copy.body]),
    ]));
  }

  function errorCopy(err, owner, repo) {
    var name = owner && repo ? owner + "/" + repo : "that repository";
    if (!err || err.code === "NETWORK") {
      return {
        title: "Could not reach GitHub",
        body: "The request never arrived. Serve this folder over HTTP instead of opening the file directly, then try again.",
      };
    }
    if (err.code === "NOT_FOUND") {
      return {
        title: "Repository not found",
        body: "No public repository named " + name + ". It may be private, renamed, or mistyped.",
      };
    }
    if (err.code === "BAD_TOKEN") {
      return {
        title: "Token was rejected",
        body: "GitHub did not accept this token. Forget it, or paste a personal access token that can read public repositories.",
      };
    }
    if (err.code === "RATE_LIMIT") {
      return {
        title: "GitHub rate limit reached",
        body: "Unauthenticated use allows about 60 requests an hour, and one lookup takes around a dozen. Add a personal access token, or wait " + waitPhrase(err.limit && err.limit.reset) + ".",
      };
    }
    return {
      title: "GitHub could not score this repo",
      body: err.message || "Something went wrong while reading the repository.",
    };
  }

  function renderSuccess(report) {
    var score = report.score;
    var repo = report.repo;
    setStatus(repo.fullName + " scores " + score.score + " out of 100. " + score.verdict.title + ".");

    var warnings = report.warnings.slice();
    if (report.rateLimited) {
      warnings.unshift("GitHub rate-limited some requests. Missing signals scored 0 and are explained below. Add a token, or wait " + waitPhrase(report.limit && report.limit.reset) + ".");
    }
    var banner = null;
    if (warnings.length) {
      banner = h("div", { class: "banner" }, [
        h("strong", {}, ["Part of this lookup was incomplete"]),
        h("ul", {}, warnings.map(function (warning) { return h("li", {}, [warning]); })),
      ]);
    }

    var metaBits = [repo.language, repo.license, formatStars(repo.stars), shortAge(repo.pushedAt)].filter(Boolean);
    var copyBtn = h("button", { type: "button", class: "ghost" }, ["Copy share link"]);
    copyBtn.addEventListener("click", function () {
      var url = window.location.href;
      var done = function (ok) {
        copyBtn.textContent = ok ? "Link copied" : "Copy failed";
        setTimeout(function () { copyBtn.textContent = "Copy share link"; }, 1800);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () { done(true); }, function () { done(false); });
      } else done(false);
    });

    var instrument = h("section", { class: "panel instrument" }, [
      h("p", { class: "eyebrow" }, ["Contributor-readiness"]),
      h("div", { class: "ring-wrap" }, [
        scoreRing(score.score, score.verdict.id),
        h("div", { class: "score-readout" }, [
          h("p", { class: "score-number" }, [
            String(score.score),
            h("span", {}, ["/100"]),
          ]),
        ]),
      ]),
      h("h2", { class: "verdict" }, [score.verdict.title]),
      h("p", {}, [score.verdict.blurb]),
      h("h3", {}, [
        h("a", { class: "repo-link", href: repo.htmlUrl, target: "_blank", rel: "noopener noreferrer" }, [repo.fullName]),
      ]),
      repo.description ? h("p", { class: "repo-desc" }, [repo.description]) : null,
      h("p", { class: "meta" }, [metaBits.join(" · ")]),
      h("div", { class: "actions" }, [
        copyBtn,
        h("a", { href: repo.htmlUrl, target: "_blank", rel: "noopener noreferrer" }, ["View on GitHub"]),
      ]),
      h("p", { class: "legend" }, ["85+ ready. 70+ welcoming. 50+ possible. 30+ thin onboarding."]),
    ]);

    var factors = score.breakdown.map(function (item, index) {
      var meter = h("div", {
        class: "meter",
        role: "meter",
        "aria-valuemin": "0",
        "aria-valuemax": String(item.max),
        "aria-valuenow": String(item.points),
        "aria-label": item.label,
      });
      var fill = h("span", { class: "meter-fill" });
      fill.style.width = (item.max ? (item.points / item.max) * 100 : 0) + "%";
      meter.appendChild(fill);
      return h("li", { class: "factor" }, [
        h("span", { class: "factor-index" }, [index < 9 ? "0" + (index + 1) : String(index + 1)]),
        h("h3", {}, [item.label]),
        h("span", { class: "points" }, [item.points + "/" + item.max]),
        meter,
        h("p", { class: "detail" }, [item.detail]),
      ]);
    });

    var breakdown = h("section", { class: "panel breakdown" }, [
      h("h2", {}, ["How this score was built"]),
      h("p", { class: "method" }, ["Nine public signals add up to 100. A maintainer reply is the first comment from an owner, member, or collaborator, skipping bots and the person who opened the thread. Review summaries are not in the sample."]),
      h("ol", {}, factors),
    ]);

    var cards;
    if (!report.issues.length) {
      cards = h("div", { class: "empty-issues" }, [
        h("h3", {}, ["No starter issue matched"]),
        h("p", {}, ["Nothing in the newest open issues was unassigned and labeled good first issue, help wanted, or hacktoberfest. The repo can still be worth watching."]),
      ]);
    } else {
      cards = h("div", { class: "cards" }, report.issues.map(function (issue, index) {
        return h("article", { class: "issue" }, [
          h("p", { class: "issue-kicker" }, [
            h("span", {}, [index < 9 ? "0" + (index + 1) : String(index + 1)]),
            "Issue #" + issue.number,
          ]),
          h("h3", {}, [issue.title]),
          issue.labels.length ? h("ul", { class: "pills" }, issue.labels.map(labelPill)) : null,
          h("p", { class: "why" }, [
            h("strong", {}, ["Why"]),
            issue.why,
          ]),
          h("a", {
            href: issueUrl(report.owner, report.repoName, issue),
            target: "_blank",
            rel: "noopener noreferrer",
          }, ["Open on GitHub"]),
        ]);
      }));
    }

    var limit = report.limit;
    var limitText = "GitHub did not report a core rate limit on this lookup.";
    if (limit && limit.remaining != null && Number.isFinite(Number(limit.remaining))) {
      var remaining = Number(limit.remaining);
      limitText = "GitHub core rate limit: " + remaining + " request" + (remaining === 1 ? "" : "s") + " left, resetting " + resetPhrase(limit.reset) + ".";
      if (remaining < 15) limitText += " That may not cover another full lookup without a token.";
    }

    var starters = h("section", { class: "panel starters" }, [
      h("h2", {}, ["Three places to start"]),
      h("p", { class: "method" }, ["Unassigned issues with a starter label, few comments, and a recent opening date rank first."]),
      cards,
      h("p", { class: "footnote" }, ["Recommendations come from the newest 100 open issues on each recognized label. Assigned issues and pull requests are left out."]),
      h("p", { class: "limit-note" }, [limitText]),
    ]);

    var layout = h("div", { class: "score-layout" }, [instrument, breakdown]);
    resultEl.replaceChildren();
    if (banner) resultEl.appendChild(banner);
    resultEl.appendChild(layout);
    resultEl.appendChild(starters);
  }

  function tokenForRequest() {
    var typed = normalizeToken(tokenInput.value);
    if (typed) {
      writeStorage(TOKEN_KEY, typed);
      tokenInput.value = "";
      setTokenStatus();
      return typed;
    }
    return readStorage(TOKEN_KEY);
  }

  async function submit(raw) {
    if (!scoring) {
      setFormError("Scoring failed to load. Check that scoring.js is next to this page.");
      return;
    }
    var parsed = scoring.parseRepoInput(raw);
    if (!parsed) {
      setFormError("Use owner/name or a github.com repository URL.");
      return;
    }
    setFormError("");
    setRepoParam(parsed.owner + "/" + parsed.repo);
    var id = ++runId;
    if (activeController) activeController.abort();
    activeController = new AbortController();
    setBusy(true);
    renderLoading();
    setStatus("Scoring " + parsed.owner + "/" + parsed.repo + "…");
    try {
      var report = await analyze(parsed.owner, parsed.repo, tokenForRequest(), activeController.signal, function (message) {
        if (id === runId) setStatus(message);
      });
      if (id !== runId) return;
      if (report.repo.fullName) setRepoParam(report.repo.fullName);
      renderSuccess(report);
      var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      resultEl.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    } catch (err) {
      if (isAbort(err) || id !== runId) return;
      renderError(err, parsed.owner, parsed.repo);
    } finally {
      if (id === runId) setBusy(false);
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    submit(repoInput.value);
  });

  exampleButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      repoInput.value = button.getAttribute("data-repo") || "";
      submit(repoInput.value);
    });
  });

  tokenInput.addEventListener("blur", function () {
    var typed = normalizeToken(tokenInput.value);
    if (!typed) return;
    writeStorage(TOKEN_KEY, typed);
    tokenInput.value = "";
    setTokenStatus();
  });

  clearTokenBtn.addEventListener("click", function () {
    writeStorage(TOKEN_KEY, "");
    tokenInput.value = "";
    setTokenStatus();
  });

  initTheme();
  setTokenStatus();

  var initial = new URLSearchParams(window.location.search).get("repo");
  if (initial) {
    repoInput.value = initial;
    submit(initial);
  }
})();
