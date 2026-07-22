package main

import "testing"

func TestSplitQuery(t *testing.T) {
	tokens, err := splitQuery(`"Bank of Canada" housing tag:canadian since:2026-07-01 until:2026-08-01`)
	if err != nil {
		t.Fatal(err)
	}
	if len(tokens) != 5 || !tokens[0].phrase || tokens[0].value != "Bank of Canada" {
		t.Fatalf("unexpected tokens: %#v", tokens)
	}
}

func TestSplitQueryRejectsUnterminatedPhrase(t *testing.T) {
	if _, err := splitQuery(`"unfinished`); err == nil {
		t.Fatal("expected an unterminated phrase error")
	}
}

func TestBoundedInt(t *testing.T) {
	if got := boundedInt("500", 20, 1, 100); got != 100 {
		t.Fatalf("expected upper bound, got %d", got)
	}
	if got := boundedInt("invalid", 20, 1, 100); got != 20 {
		t.Fatalf("expected fallback, got %d", got)
	}
}
