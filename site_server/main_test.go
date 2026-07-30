package main

import (
	"net/url"
	"reflect"
	"testing"
	"time"
)

// The HTTP surface is a contract shared with the theme's search adapter and with
// the theme's own reference server, so the parsing rules are what these tests
// pin down: they are the part two independent clients have to agree on. The
// grammar itself is parsed once, client-side, and never here.

func params(t *testing.T, raw string) searchParams {
	t.Helper()
	values, err := url.ParseQuery(raw)
	if err != nil {
		t.Fatalf("ParseQuery(%q): %v", raw, err)
	}
	parsed, err := parseParams(values)
	if err != nil {
		t.Fatalf("parseParams(%q): %v", raw, err)
	}
	return parsed
}

func TestParseParamsCollectsRepeatedClauses(t *testing.T) {
	got := params(t, "q=canadian+housing&phrase=Bank+of+Canada&phrase=interest+rate"+
		"&tag=canadian&tag=economics&category=Twitter")
	if got.terms != "canadian housing" {
		t.Errorf("terms = %q", got.terms)
	}
	if want := []string{"Bank of Canada", "interest rate"}; !reflect.DeepEqual(got.phrases, want) {
		t.Errorf("phrases = %q, want %q", got.phrases, want)
	}
	if want := []string{"canadian", "economics"}; !reflect.DeepEqual(got.tags, want) {
		t.Errorf("tags = %q, want %q", got.tags, want)
	}
	if want := []string{"Twitter"}; !reflect.DeepEqual(got.categories, want) {
		t.Errorf("categories = %q, want %q", got.categories, want)
	}
}

func TestParseParamsAcceptsBothPagingStyles(t *testing.T) {
	cases := []struct {
		name              string
		raw               string
		page, per, offset int
	}{
		{"defaults", "", 1, defaultPerPage, 0},
		{"page and per", "page=3&per=10", 3, 10, 20},
		{"offset and limit", "offset=20&limit=10", 3, 10, 20},
		{"offset wins over page", "page=9&offset=40&per=20", 3, 20, 40},
		{"per is capped", "per=100000", 1, maxPerPage, 0},
		{"junk falls back", "page=x&per=y", 1, defaultPerPage, 0},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := params(t, c.raw)
			if got.page != c.page || got.per != c.per || got.offset != c.offset {
				t.Errorf("page/per/offset = %d/%d/%d, want %d/%d/%d",
					got.page, got.per, got.offset, c.page, c.per, c.offset)
			}
		})
	}
}

func TestParseParamsDateBounds(t *testing.T) {
	got := params(t, "since=2026-07-01&until=2026-07-02")
	if !got.since.Equal(time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("since = %s", got.since)
	}
	if got.sinceText != "2026-07-01" || got.untilText != "2026-07-02" {
		t.Errorf("bound text = %q/%q", got.sinceText, got.untilText)
	}

	for _, raw := range []string{
		"since=yesterday",
		"until=07-01-2026",
		"since=2026-07-02&until=2026-07-01",
		"since=2026-07-01&until=2026-07-01",
	} {
		values, _ := url.ParseQuery(raw)
		if _, err := parseParams(values); err == nil {
			t.Errorf("parseParams(%q) accepted; want a 400-worthy error", raw)
		}
	}
}

// A filter-only query must come back newest-first, because the theme
// server-renders page 1 of an over-limit term in Hugo's date order and this
// server serves page 2. Ranking one of them by score would make the two pages
// slices of different sequences, which repeats and skips notes.
func TestParseParamsSortsByDateOnlyWithoutText(t *testing.T) {
	for raw, want := range map[string]bool{
		"":                        true,
		"tag=canadian":            true,
		"since=2026-07-01":        true,
		"q=housing":               false,
		"phrase=Bank+of+Canada":   false,
		"tag=canadian&q=housing":  false,
		"q=housing&sort=date":     true,
		"tag=canadian&sort=score": false,
	} {
		if got := params(t, raw).sortByDate; got != want {
			t.Errorf("parseParams(%q).sortByDate = %v, want %v", raw, got, want)
		}
	}
}

func TestParseParamsDropsBlankValues(t *testing.T) {
	got := params(t, "tag=&tag=+&tag=canadian&category=&phrase=")
	if want := []string{"canadian"}; !reflect.DeepEqual(got.tags, want) {
		t.Errorf("tags = %q, want %q", got.tags, want)
	}
	if len(got.categories) != 0 || len(got.phrases) != 0 {
		t.Errorf("categories = %q, phrases = %q; want both empty", got.categories, got.phrases)
	}
}

// The echoed query has to parse back to the query that produced it, so a value
// containing a space comes back quoted.
func TestDescribeRoundTripsQuoting(t *testing.T) {
	got := describe(searchParams{
		categories: []string{"Field notes"},
		tags:       []string{"canadian", "two words"},
		sinceText:  "2026-07-01",
		untilText:  "2026-07-02",
		phrases:    []string{"Bank of Canada"},
		terms:      "interest rate",
	})
	want := `category:"Field notes" tag:canadian tag:"two words" ` +
		`since:2026-07-01 until:2026-07-02 "Bank of Canada" interest rate`
	if got != want {
		t.Errorf("describe() =\n  %s\nwant\n  %s", got, want)
	}
}

func TestBoundedInt(t *testing.T) {
	if got := boundedInt("500", 20, 1, 100); got != 100 {
		t.Fatalf("expected upper bound, got %d", got)
	}
	if got := boundedInt("invalid", 20, 1, 100); got != 20 {
		t.Fatalf("expected fallback, got %d", got)
	}
	if got := boundedInt("-1", 20, 0, 100); got != 0 {
		t.Fatalf("expected lower bound, got %d", got)
	}
}
