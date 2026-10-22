// The emergent program: a 6-deep chain, mutual recursion, and an unreachable island.
public class Prog {
    static int step1() {
        return step2() + 1;
    }

    static int step2() {
        return step3() + 1;
    }

    static int step3() {
        return step4() + 1;
    }

    static int step4() {
        return step5() + 1;
    }

    static int step5() {
        return step6() + 1;
    }

    static int step6() {
        return 1;
    }

    static int ping() {
        return pong() + 1;
    }

    static int pong() {
        return ping() + 1;
    }

    static int lonely_a() {
        return lonely_b() + 1;
    }

    static int lonely_b() {
        return lonely_a() + 1;
    }

    public static void main() {
        step1();
        ping();
    }
}
