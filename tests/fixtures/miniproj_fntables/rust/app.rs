fn alpha_handler(x: i32) -> i32 { x + 1 }
fn on_beta(x: i32) -> i32 { x * 2 }

static HANDLERS: &[(&str, fn(i32) -> i32)] = &[("alpha", alpha_handler), ("beta", on_beta)];

fn first_step(x: i32) -> i32 { x }
fn second_step(x: i32) -> i32 { x }

static PIPE: [fn(i32) -> i32; 2] = [first_step, second_step];

pub fn dispatch(i: usize, x: i32) -> i32 { PIPE[i](x) }
