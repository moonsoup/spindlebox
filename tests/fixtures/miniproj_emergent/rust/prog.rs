//! The emergent program: a 6-deep chain, mutual recursion, and an unreachable island.

pub fn step1() -> i64 {
    step2() + 1
}

pub fn step2() -> i64 {
    step3() + 1
}

pub fn step3() -> i64 {
    step4() + 1
}

pub fn step4() -> i64 {
    step5() + 1
}

pub fn step5() -> i64 {
    step6() + 1
}

pub fn step6() -> i64 {
    1
}

pub fn ping() -> i64 {
    pong() + 1
}

pub fn pong() -> i64 {
    ping() + 1
}

pub fn lonely_a() -> i64 {
    lonely_b() + 1
}

pub fn lonely_b() -> i64 {
    lonely_a() + 1
}

pub fn main() {
    step1();
    ping();
}
