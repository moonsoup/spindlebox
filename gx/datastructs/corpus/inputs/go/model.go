// Package model is the synthetic data model for the data-structure translation round (gx/datastructs).
package model

type Money struct {
	amount   int64
	currency string
}

type LineItem struct {
	sku   string
	qty   int64
	price Money
}

type Status int

const (
	Pending Status = iota
	Paid
	Shipped
)

// Payment is a closed sum type: only Card, Transfer and Cash implement it.
type Payment interface{ isPayment() }

type Card struct{ last4 string }
type Transfer struct{ iban string }
type Cash struct{}

func (Card) isPayment()     {}
func (Transfer) isPayment() {}
func (Cash) isPayment()     {}

type Order struct {
	id      string
	items   []LineItem
	status  Status
	payment *Payment
	tags    map[string][]string
}

type Tree[T any] struct {
	value    T
	children []Tree[T]
}

type Page[T any] struct {
	items []T
	next  *string
}

func total(order Order) Money {
	var sum int64
	for _, i := range order.items {
		sum += i.qty * i.price.amount
	}
	return Money{amount: sum, currency: order.items[0].price.currency}
}
