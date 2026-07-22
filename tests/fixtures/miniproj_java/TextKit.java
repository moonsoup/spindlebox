package com.example.textkit;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;

/** Text utilities mirroring the other miniproj fixtures. */
public class TextKit {
    private int count;

    /** Build a kit starting at a count. */
    public TextKit(int start) {
        this.count = start;
    }

    /** readLines reads lines from a file. */
    public static List<String> readLines(String path) {
        try {
            return Files.readAllLines(Path.of(path));
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }

    /** Where the app lives. */
    public static String home() {
        return System.getenv("APP_HOME");
    }

    /** Bump the count by each extra, mutating instance state. */
    public int bump(String s, int... extras) {
        this.count += s.length();
        return this.count;
    }

    /** Length plus a captured local. */
    public int measure(String s) {
        int base = this.count;
        Function<String, Integer> len = t -> t.length() + base;
        return len.apply(s);
    }

    public Optional<Map<String, Integer>> lookup(String key) {
        helperThing(key);
        return Optional.empty();
    }

    private void helperThing(String k) {
    }
}
