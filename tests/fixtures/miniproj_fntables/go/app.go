package app

func alphaHandler(x int) int { return x + 1 }
func onBeta(x int) int      { return x * 2 }

var HANDLERS = map[string]func(int) int{"alpha": alphaHandler, "beta": onBeta}

func dispatch(kind string, x int) int { return HANDLERS[kind](x) }

func firstStep(x int) int  { return x }
func secondStep(x int) int { return x }

var PIPE = []func(int) int{firstStep, secondStep}
