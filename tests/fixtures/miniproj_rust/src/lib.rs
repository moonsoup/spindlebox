use serde_json::Value;
use std::env;

/// Read lines from a file.
pub fn read_lines(path: String) -> Vec<String> {
    std::fs::read_to_string(&path)
        .unwrap_or_default()
        .lines()
        .map(String::from)
        .collect()
}

pub fn home() -> String {
    env::var("APP_HOME").unwrap_or_default()
}

pub fn parse_blob(blob: &str) -> Value {
    serde_json::from_str(blob).unwrap()
}

pub struct Reader {
    path: String,
    count: i64,
}

impl Reader {
    pub fn read(&mut self) -> Vec<String> {
        self.count += 1;
        read_lines(self.path.clone())
    }

    pub fn peek(&self) -> String {
        self.path.clone()
    }
}

pub fn make_adder(n: i64) -> impl Fn(i64) -> i64 {
    move |x| x + n
}
