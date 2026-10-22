//! The parity program: a tiny pipeline that every indexed language spells the same way.

/// Produce the raw lines.
pub fn load() -> Vec<String> {
    clean()
}

/// Normalize the lines.
pub fn clean() -> Vec<String> {
    vec![String::from("a"), String::from("b")]
}

/// Count the lines (through a prelude builtin).
pub fn summarize() -> i64 {
    let n = Some(clean().len());
    n.unwrap_or(0) as i64
}

pub fn compute_alpha() -> i64 {
    clean().len() as i64 + 1
}

pub fn compute_beta() -> i64 {
    clean().len() as i64 + 2
}

/// Nobody calls this and nothing consumes its result.
pub fn island() -> i64 {
    7
}

pub fn main() {
    load();
    summarize();
    does_not_exist();
}
