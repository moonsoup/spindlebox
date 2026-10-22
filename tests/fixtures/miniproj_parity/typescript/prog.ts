// The parity program: a tiny pipeline that every indexed language spells the same way.

/** Produce the raw lines. */
export function load(): string[] {
  return clean();
}

/** Normalize the lines. */
export function clean(): string[] {
  return ["a", "b"];
}

/** Count the lines (through a language global). */
export function summarize(): number {
  return parseInt(String(clean().length), 10);
}

export function compute_alpha(): number {
  return clean().length + 1;
}

export function compute_beta(): number {
  return clean().length + 2;
}

/** Nobody calls this and nothing consumes its result. */
export function island(): number {
  return 7;
}

export function main(): void {
  load();
  summarize();
  does_not_exist();
}
