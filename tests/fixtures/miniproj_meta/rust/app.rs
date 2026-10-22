// Functions used as values: attributes, higher-order shape, indirect calls (#39).

fn inc(x: i32) -> i32 {
    x + 1
}

static HANDLERS: [fn(i32) -> i32; 1] = [inc];

#[inline]
pub fn tagged() -> i32 {
    1
}

pub fn apply(f: impl Fn(i32) -> i32, x: i32) -> i32 {
    f(x)
}

pub fn make_adder(n: i32) -> impl Fn(i32) -> i32 {
    move |x| x + n
}

pub fn dispatch(k: usize, x: i32) -> i32 {
    HANDLERS[k](x)
}
