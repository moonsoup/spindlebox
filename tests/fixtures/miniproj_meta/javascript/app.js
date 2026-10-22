// Functions used as values: decorators, higher-order shape, indirect calls (#39).

function inc(x) {
  return x + 1;
}

const HANDLERS = { inc: inc };

class Widget {
  @deco
  tagged() {
    return 1;
  }
}

function apply(f, x) {
  return f(x);
}

function make_adder(n) {
  return (x) => x + n;
}

function dispatch(k, x) {
  return HANDLERS[k](x);
}

module.exports = { Widget, apply, make_adder, dispatch };
