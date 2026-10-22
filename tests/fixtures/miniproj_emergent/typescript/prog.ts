// The emergent program: a 6-deep chain, mutual recursion, and an unreachable island.

export function step1(): number {
  return step2() + 1;
}

export function step2(): number {
  return step3() + 1;
}

export function step3(): number {
  return step4() + 1;
}

export function step4(): number {
  return step5() + 1;
}

export function step5(): number {
  return step6() + 1;
}

export function step6(): number {
  return 1;
}

export function ping(): number {
  return pong() + 1;
}

export function pong(): number {
  return ping() + 1;
}

export function lonely_a(): number {
  return lonely_b() + 1;
}

export function lonely_b(): number {
  return lonely_a() + 1;
}

export function main(): void {
  step1();
  ping();
}
