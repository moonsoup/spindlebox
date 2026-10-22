// Package app: functions used as values (#39).
package app

func inc(x int) int {
	return x + 1
}

var HANDLERS = map[string]func(int) int{"inc": inc}

func apply(f func(int) int, x int) int {
	return f(x)
}

func make_adder(n int) func(int) int {
	return func(x int) int {
		return x + n
	}
}

func dispatch(k string, x int) int {
	return HANDLERS[k](x)
}

func dispatch_literal(x int) int {
	return HANDLERS["inc"](x)
}
