'use strict';

const Module = require('module');
const path = require('path');

function normalize(mod) {
  if (mod == null || typeof mod !== 'object') {
    throw new Error('implementation module.exports is not an object');
  }
  const compareAliases = ['compareVersions', 'compare', 'cmp', 'compareVersion'];
  const maxAliases = ['maxSatisfying', 'max_satisfying', 'maxSatisfy', 'maxSat'];
  let compareVersions;
  let maxSatisfying;
  for (const key of compareAliases) {
    if (typeof mod[key] === 'function') {
      compareVersions = mod[key];
      break;
    }
  }
  for (const key of maxAliases) {
    if (typeof mod[key] === 'function') {
      maxSatisfying = mod[key];
      break;
    }
  }
  if (!compareVersions || !maxSatisfying) {
    const names = Object.keys(mod).filter((key) => typeof mod[key] === 'function');
    throw new Error('could not normalise exports; functions: ' + names.join(', '));
  }
  return { compareVersions, maxSatisfying };
}

const implPath = process.env.JUDGE_IMPL;
if (!implPath) {
  throw new Error('JUDGE_IMPL must be the absolute path of the implementation under test');
}

const implementation = normalize(require(path.resolve(implPath)));
const originalRequire = Module.prototype.require;

Module.prototype.require = function patchedRequire(id) {
  const caller = this.filename ? path.basename(this.filename) : '';
  const target = path.basename(String(id));
  if (caller === 'semver.test.js' && (target === 'semver' || target === 'semver.js')) {
    return implementation;
  }
  return originalRequire.apply(this, arguments);
};
