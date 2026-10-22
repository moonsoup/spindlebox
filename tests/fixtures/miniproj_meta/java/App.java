// Functions used as values: annotations and higher-order shape (#39).
import java.util.function.Function;

public class App {
    static int inc(int x) {
        return x + 1;
    }

    @Deprecated
    public static int tagged() {
        return 1;
    }

    public static int apply(Function<Integer, Integer> f, int x) {
        return f.apply(x);
    }

    public static Function<Integer, Integer> make_adder(int n) {
        return x -> x + n;
    }
}
