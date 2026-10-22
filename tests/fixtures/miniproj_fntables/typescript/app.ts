function alphaHandler(x: number): number { return x + 1; }
function onBeta(x: number): number { return x * 2; }

const HANDLERS: Record<string, (x: number) => number> = { alpha: alphaHandler, "beta": onBeta };

function dispatch(kind: string, x: number): number { return HANDLERS[kind](x); }

function firstStep(x: number): number { return x; }
function secondStep(x: number): number { return x; }

export const PIPE = [firstStep, secondStep];
