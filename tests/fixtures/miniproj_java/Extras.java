package com.example.textkit;

import java.util.List;
import java.util.function.BiFunction;

enum Color { RED, GREEN }

record Point(int x, int y) {}

@interface Marker {}

class Extras {
    static int sumLengths(List<String> words) {
        int total = 0;
        for (String w : words) {
            total += w.length();
        }
        int i = 0;
        i++;
        BiFunction<Integer, Integer, Integer> add = (a, b) -> a + b;
        return total + add.apply(i, i);
    }
}
