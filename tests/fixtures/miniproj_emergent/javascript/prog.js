// The emergent program: a 6-deep chain, mutual recursion, and an unreachable island.

function step1() {
  return step2() + 1;
}

function step2() {
  return step3() + 1;
}

function step3() {
  return step4() + 1;
}

function step4() {
  return step5() + 1;
}

function step5() {
  return step6() + 1;
}

function step6() {
  return 1;
}

function ping() {
  return pong() + 1;
}

function pong() {
  return ping() + 1;
}

function lonely_a() {
  return lonely_b() + 1;
}

function lonely_b() {
  return lonely_a() + 1;
}

function main() {
  step1();
  ping();
}
