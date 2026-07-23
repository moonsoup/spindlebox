// Plain-JS constructs the typescript file can't cover: require, var-assigned
// functions, object-literal methods, update expressions, rest/default params.
const fs = require("fs");

function readLines(path) {
  return fs.readFileSync(path, "utf8").split("\n");
}

const slugify = function (text) {
  return text.toLowerCase().replace(/\s+/g, "-");
};

const tally = (start = 0, ...extras) => {
  let total = start;
  for (const e of extras) total += e;
  return total;
};

const api = {
  fetch(url) {
    return Promise.resolve(url);
  },
};

function makeTicker() {
  let ticks = 0;
  return function tick() {
    ticks++;
    return ticks;
  };
}

module.exports = { readLines, slugify, tally, api, makeTicker };

class Store {
  constructor() { this.items = []; }
  add(item) { this.items.push(item); }
}
const Registry = class { get(k) { return k; } };
function* idGen() { let i = 0; while (true) yield i++; }
const pager = function* (n) { yield n; };
