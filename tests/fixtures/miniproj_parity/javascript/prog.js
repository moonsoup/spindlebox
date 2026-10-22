// The parity program: a tiny pipeline that every indexed language spells the same way.

/** Produce the raw lines. */
function load() {
  return clean();
}

/** Normalize the lines. */
function clean() {
  return ["a", "b"];
}

/** Count the lines (through a language global). */
function summarize() {
  return parseInt(String(clean().length), 10);
}

function compute_alpha() {
  return clean().length + 1;
}

function compute_beta() {
  return clean().length + 2;
}

/** Nobody calls this and nothing consumes its result. */
function island() {
  return 7;
}

function main() {
  load();
  summarize();
  does_not_exist();
}
