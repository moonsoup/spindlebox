// The emergent program: a 6-deep chain, mutual recursion, and an unreachable island.
package main

func step1() int {
	return step2() + 1
}

func step2() int {
	return step3() + 1
}

func step3() int {
	return step4() + 1
}

func step4() int {
	return step5() + 1
}

func step5() int {
	return step6() + 1
}

func step6() int {
	return 1
}

func ping() int {
	return pong() + 1
}

func pong() int {
	return ping() + 1
}

func lonely_a() int {
	return lonely_b() + 1
}

func lonely_b() int {
	return lonely_a() + 1
}

func main() {
	step1()
	ping()
}
