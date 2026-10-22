// app is a synthetic Go program for issue #38: Go builtins and Go entry points.
package app

import "fmt"

func main() {
	buf := make([]int, 0)
	buf = append(buf, len(buf))
	if len(buf) > 9 {
		panic("full")
	}
	fmt.Println(buf)
	frobnicate_typo(buf)
}

// init runs before main: a Go entry point no in-index caller reaches.
func init() {
}

// The three below are Python entry-point spellings. In Go they are ordinary
// functions with no caller, so they are dead.
func setup() {
}

func cmd_run() {
}

func handle_event() {
}
