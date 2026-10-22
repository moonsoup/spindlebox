#!/usr/bin/env bash
# Nested function definitions: the inner one's parent is the outer (#39).

make_adder() {
    adder() {
        echo $(( $1 + 1 ))
    }
    adder "$1"
}

make_adder 1
