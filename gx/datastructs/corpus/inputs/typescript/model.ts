// Synthetic data model for the data-structure translation round (gx/datastructs).

export interface Money {
  amount: number;
  currency: string;
}

export interface LineItem {
  sku: string;
  qty: number;
  price: Money;
}

export enum Status {
  Pending,
  Paid,
  Shipped,
}

export type Payment =
  | { kind: "Card"; last4: string }
  | { kind: "Transfer"; iban: string }
  | { kind: "Cash" };

export interface Order {
  id: string;
  items: LineItem[];
  status: Status;
  payment: Payment | null;
  tags: Record<string, string[]>;
}

export interface Tree<T> {
  value: T;
  children: Tree<T>[];
}

export interface Page<T> {
  items: T[];
  next: string | null;
}

export function total(order: Order): Money {
  const amount = order.items.reduce((s, i) => s + i.qty * i.price.amount, 0);
  return { amount, currency: order.items[0].price.currency };
}
