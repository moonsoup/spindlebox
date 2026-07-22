package main

import (
	"os"
	"strings"

	"github.com/pkg/errors"
)

// ReadLines reads lines from a file.
func ReadLines(path string) []string {
	data, err := os.ReadFile(path)
	if err != nil {
		panic(errors.Wrap(err, "read"))
	}
	return strings.Split(string(data), "\n")
}

func ReadAll(path string) ([]string, error) {
	return ReadLines(path), nil
}

func Home() string {
	return os.Getenv("APP_HOME")
}

func MakeCounter() func() int {
	count := 0
	return func() int {
		count++
		return count
	}
}

type Reader struct {
	path string
}

func (r *Reader) Read() []string {
	return ReadLines(r.path)
}
