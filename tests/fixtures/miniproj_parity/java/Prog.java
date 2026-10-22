// The parity program: a tiny pipeline that every indexed language spells the same way.
import java.util.List;

public class Prog {
    /** Produce the raw lines. */
    static List<String> load() {
        return clean();
    }

    /** Normalize the lines. */
    static List<String> clean() {
        return List.of("a", "b");
    }

    /** Count the lines. */
    static int summarize() {
        return clean().size();
    }

    static int compute_alpha() {
        return clean().size() + 1;
    }

    static int compute_beta() {
        return clean().size() + 2;
    }

    /** Nobody calls this and nothing consumes its result. */
    static int island() {
        return 7;
    }

    public static void main() {
        load();
        summarize();
        does_not_exist();
    }
}
