import { readFileSync } from "fs";
import axios from "axios";

export function readLines(path: string): string[] {
  return readFileSync(path, "utf8").split("\n");
}

export function makeCounter(): () => number {
  let count = 0;
  return function bump(): number {
    count += 1;
    return count;
  };
}

export class Reader {
  path: string = "";
  count: number = 0;

  read(): string[] {
    this.count += 1;
    return readLines(this.path);
  }

  peek(): string {
    return this.path;
  }
}

export const home = (): string => process.env.APP_HOME ?? "";

export function fetchIt(url: string): Promise<string> {
  return axios.get(url).then((r: any) => r.data);
}

export function* pages(n: number): Generator<number> {
  let i = 0;
  while (i < n) { yield i; i++; }
}
export const genExpr = function* (s: string) { yield s; };
export function reset(flag: boolean): boolean {
  let state = true;
  state = flag;
  return state;
}
