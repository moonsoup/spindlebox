//! Synthetic data model for the data-structure translation round (gx/datastructs).
use std::collections::HashMap;

pub struct Money {
    pub amount: i64,
    pub currency: String,
}

pub struct LineItem {
    pub sku: String,
    pub qty: i64,
    pub price: Money,
}

pub enum Status {
    Pending,
    Paid,
    Shipped,
}

pub enum Payment {
    Card { last4: String },
    Transfer { iban: String },
    Cash,
}

pub struct Order {
    pub id: String,
    pub items: Vec<LineItem>,
    pub status: Status,
    pub payment: Option<Payment>,
    pub tags: HashMap<String, Vec<String>>,
}

pub struct Tree<T> {
    pub value: T,
    pub children: Vec<Tree<T>>,
}

pub struct Page<T> {
    pub items: Vec<T>,
    pub next: Option<String>,
}

pub fn total(order: Order) -> Money {
    let amount = order.items.iter().map(|i| i.qty * i.price.amount).sum();
    let currency = order.items[0].price.currency.clone();
    Money { amount, currency }
}
