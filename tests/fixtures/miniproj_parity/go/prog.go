// The parity program: a tiny pipeline that every indexed language spells the same way.
package main

// load produces the raw lines.
func load() []string {
	return clean()
}

// clean normalizes the lines.
func clean() []string {
	return []string{"a", "b"}
}

// summarize counts the lines (through a language builtin).
func summarize() int {
	return len(clean())
}

func compute_alpha() int {
	return len(clean()) + 1
}

func compute_beta() int {
	return len(clean()) + 2
}

// island: nobody calls this and nothing consumes its result.
func island() int {
	return 7
}

func main() {
	load()
	summarize()
	does_not_exist()
}
