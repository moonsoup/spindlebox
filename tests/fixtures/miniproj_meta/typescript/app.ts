// Functions used as values: decorators, higher-order shape, indirect calls (#39).

function inc(x: number): number {
  return x + 1;
}

const HANDLERS: Record<string, (x: number) => number> = { inc: inc };

class Widget {
  @deco()
  tagged(): number {
    return 1;
  }
}

export function apply(f: (x: number) => number, x: number): number {
  return f(x);
}

export function make_adder(n: number): (x: number) => number {
  return (x: number) => x + n;
}

export function dispatch(k: string, x: number): number {
  return HANDLERS[k](x);
}
