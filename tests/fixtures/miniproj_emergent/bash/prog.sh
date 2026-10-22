#!/bin/bash
# The emergent program: a 6-deep chain, mutual recursion, and an unreachable island.

step1() {
  step2
}

step2() {
  step3
}

step3() {
  step4
}

step4() {
  step5
}

step5() {
  step6
}

step6() {
  echo 1
}

ping() {
  pong
}

pong() {
  ping
}

lonely_a() {
  lonely_b
}

lonely_b() {
  lonely_a
}

main() {
  step1
  ping
}

main "$@"
