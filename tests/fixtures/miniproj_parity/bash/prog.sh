#!/bin/bash
# The parity program: a tiny pipeline that every indexed language spells the same way.

# Produce the raw lines.
load() {
  clean
}

# Normalize the lines.
clean() {
  echo "a"
  echo "b"
}

# Count the lines (through a shell builtin).
summarize() {
  clean | wc -l
}

compute_alpha() {
  echo $(( $(clean | wc -l) + 1 ))
}

compute_beta() {
  echo $(( $(clean | wc -l) + 2 ))
}

# Nobody calls this and nothing consumes its result.
island() {
  echo 7
}

main() {
  load
  summarize
  does_not_exist
}

main "$@"
