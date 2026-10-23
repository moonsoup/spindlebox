"""Synthetic data model for the data-structure translation round (gx/datastructs)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class Money:
    amount: int
    currency: str


@dataclass
class LineItem:
    sku: str
    qty: int
    price: Money


class Status(Enum):
    Pending = "pending"
    Paid = "paid"
    Shipped = "shipped"


@dataclass
class Card:
    last4: str


@dataclass
class Transfer:
    iban: str


@dataclass
class Cash:
    pass


Payment = Card | Transfer | Cash


@dataclass
class Order:
    id: str
    items: list[LineItem]
    status: Status
    payment: Optional[Payment]
    tags: dict[str, list[str]]


@dataclass
class Tree(Generic[T]):
    value: T
    children: list[Tree[T]]


@dataclass
class Page(Generic[T]):
    items: list[T]
    next: Optional[str]


def total(order: Order) -> Money:
    return Money(sum(i.qty * i.price.amount for i in order.items), order.items[0].price.currency)
