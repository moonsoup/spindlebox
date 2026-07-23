//! Constructs lib.rs doesn't cover: mod blocks, consuming self, nested fns.

pub mod inner {
    pub mod deeper {
        /// Doubles a value inside a nested module.
        pub fn double(x: i64) -> i64 {
            x * 2
        }
    }

    pub struct Token {
        pub value: String,
    }

    impl Token {
        pub fn consume(self) -> String {
            self.value
        }
    }
}

pub fn outer(r#type: String) -> String {
    fn helper(s: String) -> String {
        s.trim().to_string()
    }
    helper(r#type)
}
