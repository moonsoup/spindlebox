function alphaHandler(x) { return x + 1; }
function onBeta(x) { return x * 2; }

const HANDLERS = { alpha: alphaHandler, "beta": onBeta };

function dispatch(kind, x) { return HANDLERS[kind](x); }

function firstStep(x) { return x; }
function secondStep(x) { return x; }

export const PIPE = [firstStep, secondStep];
