// Synthetic data model for the data-structure translation round (gx/datastructs).
import java.util.List;
import java.util.Map;
import java.util.Optional;

public class Model {
    public record Money(long amount, String currency) {}

    public record LineItem(String sku, long qty, Money price) {}

    public enum Status { Pending, Paid, Shipped }

    public sealed interface Payment permits Card, Transfer, Cash {}

    public record Card(String last4) implements Payment {}

    public record Transfer(String iban) implements Payment {}

    public record Cash() implements Payment {}

    public record Order(String id, List<LineItem> items, Status status, Optional<Payment> payment,
                        Map<String, List<String>> tags) {}

    public record Tree<T>(T value, List<Tree<T>> children) {}

    public record Page<T>(List<T> items, Optional<String> next) {}

    public static Money total(Order order) {
        long amount = 0;
        for (LineItem i : order.items()) amount += i.qty() * i.price().amount();
        return new Money(amount, order.items().get(0).price().currency());
    }
}
