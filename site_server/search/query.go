package search

import (
	"errors"
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/blugelabs/bluge"
	"github.com/blugelabs/bluge/search"
)

type sourceRecord struct {
	ID       int      `json:"id"`
	URL      string   `json:"url"`
	Title    string   `json:"title"`
	Date     string   `json:"date"`
	Body     string   `json:"body"`
	Summary  string   `json:"summary"`
	Category string   `json:"category"`
	Tags     []string `json:"tags"`
	// DisplayTags are the tags a result card shows: the ones actually written in
	// the note. `tags` above holds those plus every generated content word, which
	// is what `tag:` searches, but a card showing four random content words is
	// noise — and storing 180 tags per note for display cost 23% of the index.
	DisplayTags []string `json:"displayTags"`
	ReadingTime int      `json:"readingTime"`
}

// searchResult is the shape the theme's assets/js/search/backends/bluge.js
// renders. These field names are the contract; changing one means changing the
// adapter, and the theme's own reference server in search-server/ alongside it.
type searchResult struct {
	Title       string   `json:"title"`
	Summary     string   `json:"summary"`
	URL         string   `json:"url"`
	Category    string   `json:"category"`
	Tags        []string `json:"tags"`
	Date        string   `json:"date"`
	ReadingTime int      `json:"readingTime"`
}

type searchResponse struct {
	Backend string         `json:"backend"`
	Query   string         `json:"query"`
	Total   uint64         `json:"total"`
	Page    int            `json:"page"`
	Per     int            `json:"per"`
	Offset  int            `json:"offset"`
	Limit   int            `json:"limit"`
	Results []searchResult `json:"results"`
}

// searchParams is one already-parsed query. The grammar is parsed exactly once,
// client-side, in the theme's assets/js/search/query.js; this server receives
// fields and never re-parses `tag:` prefixes or quotes. Repeated fields are
// ANDed, which is what repeating a clause means in the grammar.
type searchParams struct {
	terms      string
	phrases    []string
	categories []string
	tags       []string
	since      time.Time
	until      time.Time
	sinceText  string
	untilText  string
	page       int
	per        int
	offset     int
	sortByDate bool
}

type indexStamp struct {
	SourceSize    int64 `json:"source_size"`
	SourceModUnix int64 `json:"source_mod_unix"`
}

const (
	defaultPerPage = 20
	maxPerPage     = 100
	maxOffset      = 10_000_000
	dateLayout     = "2006-01-02"
	maxDisplayTags = 8
)

func parseParams(values url.Values) (searchParams, error) {
	params := searchParams{
		terms:      strings.TrimSpace(values.Get("q")),
		phrases:    nonEmpty(values["phrase"]),
		categories: nonEmpty(values["category"]),
		tags:       nonEmpty(values["tag"]),
		sinceText:  strings.TrimSpace(values.Get("since")),
		untilText:  strings.TrimSpace(values.Get("until")),
	}

	for name, raw := range map[string]string{"since": params.sinceText, "until": params.untilText} {
		if raw == "" {
			continue
		}
		parsed, err := time.Parse(dateLayout, raw)
		if err != nil {
			return params, fmt.Errorf("%s: expected YYYY-MM-DD", name)
		}
		if name == "since" {
			params.since = parsed.UTC()
		} else {
			params.until = parsed.UTC()
		}
	}
	if !params.since.IsZero() && !params.until.IsZero() && !params.since.Before(params.until) {
		return params, errors.New("since: must be earlier than until:")
	}

	// `limit` is the alias for `per`; whichever is present wins, and per bounds
	// the response size either way.
	perRaw := values.Get("per")
	if perRaw == "" {
		perRaw = values.Get("limit")
	}
	params.per = boundedInt(perRaw, defaultPerPage, 1, maxPerPage)

	if raw := values.Get("offset"); raw != "" {
		params.offset = boundedInt(raw, 0, 0, maxOffset)
		params.page = params.offset/params.per + 1
	} else {
		params.page = boundedInt(values.Get("page"), 1, 1, 1<<20)
		params.offset = (params.page - 1) * params.per
	}

	// Newest first for every query, not only for filter-only ones. An archive is
	// read chronologically: relevance ordering puts the most recent note at an
	// unpredictable position, and in a long result set the visitor would have to
	// page to the end to find it. It also keeps a server-rendered first page and
	// a searched second page in one sequence for every query shape, not just
	// some. `sort=score` is the escape hatch for a caller that wants ranking.
	params.sortByDate = values.Get("sort") != "score" && values.Get("sort") != "relevance"

	return params, nil
}

// buildQuery turns the parsed fields into one Bluge query. Repeated values are
// ANDed; a term matches the title, the summary or the body, with the title
// weighted highest.
func buildQuery(params searchParams) bluge.Query {
	boolean := bluge.NewBooleanQuery()
	clauses := 0

	for _, category := range params.categories {
		boolean.AddMust(bluge.NewTermQuery(category).SetField("category"))
		clauses++
	}
	for _, tag := range params.tags {
		boolean.AddMust(bluge.NewTermQuery(strings.ToLower(tag)).SetField("tag"))
		clauses++
	}
	if params.terms != "" {
		// Every term must appear, in one field or another.
		any := bluge.NewBooleanQuery().SetMinShould(1)
		any.AddShould(
			bluge.NewMatchQuery(params.terms).SetField("title").
				SetOperator(bluge.MatchQueryOperatorAnd).SetBoost(4),
			bluge.NewMatchQuery(params.terms).SetField("summary").
				SetOperator(bluge.MatchQueryOperatorAnd).SetBoost(2),
			bluge.NewMatchQuery(params.terms).SetField("body").
				SetOperator(bluge.MatchQueryOperatorAnd),
		)
		boolean.AddMust(any)
		clauses++
	}
	for _, phrase := range params.phrases {
		any := bluge.NewBooleanQuery().SetMinShould(1)
		any.AddShould(
			bluge.NewMatchPhraseQuery(phrase).SetField("title").SetBoost(4),
			bluge.NewMatchPhraseQuery(phrase).SetField("summary").SetBoost(2),
			bluge.NewMatchPhraseQuery(phrase).SetField("body"),
		)
		boolean.AddMust(any)
		clauses++
	}
	if !params.since.IsZero() || !params.until.IsZero() {
		// since is inclusive and until exclusive, so one day is
		// since:D until:D+1. Dates are indexed as real timestamps, so a note's
		// time of day is compared, not just its calendar date.
		boolean.AddMust(
			bluge.NewDateRangeInclusiveQuery(params.since, params.until, true, false).
				SetField("date"))
		clauses++
	}

	if clauses == 0 {
		return bluge.NewMatchAllQuery()
	}
	return boolean
}

func toResult(match *search.DocumentMatch) (searchResult, error) {
	var result searchResult
	var tags []string
	err := match.VisitStoredFields(func(field string, value []byte) bool {
		switch field {
		case "url":
			result.URL = string(value)
		case "title":
			result.Title = string(value)
		case "summary":
			result.Summary = string(value)
		case "date_text":
			// The contract's `date` is YYYY-MM-DD, which is what a result card
			// renders verbatim. The stored value keeps the note's full RFC 3339
			// timestamp, and the indexed `date` field keeps it for range
			// queries; only the display form is trimmed.
			result.Date = string(value)
			if len(result.Date) > 10 {
				result.Date = result.Date[:10]
			}
		case "category":
			result.Category = string(value)
		case "reading":
			result.ReadingTime, _ = strconv.Atoi(string(value))
		case "tags_display":
			if len(value) > 0 {
				tags = append(tags, strings.Split(string(value), "\t")...)
			}
		}
		return true
	})
	sort.Strings(tags)
	result.Tags = tags
	if result.Tags == nil {
		result.Tags = []string{}
	}
	return result, err
}

// describe rebuilds the grammar the visitor typed, for the response echo and the
// log line. The client sends fields, so there is no raw query to quote.
func describe(params searchParams) string {
	var parts []string
	for _, category := range params.categories {
		parts = append(parts, clause("category", category))
	}
	for _, tag := range params.tags {
		parts = append(parts, clause("tag", tag))
	}
	if params.sinceText != "" {
		parts = append(parts, "since:"+params.sinceText)
	}
	if params.untilText != "" {
		parts = append(parts, "until:"+params.untilText)
	}
	for _, phrase := range params.phrases {
		parts = append(parts, strconv.Quote(phrase))
	}
	if params.terms != "" {
		parts = append(parts, params.terms)
	}
	return strings.Join(parts, " ")
}

func clause(field, value string) string {
	if strings.ContainsAny(value, " \t\"") {
		return field + ":" + strconv.Quote(value)
	}
	return field + ":" + value
}

func nonEmpty(values []string) []string {
	out := make([]string, 0, len(values))
	for _, value := range values {
		if value = strings.TrimSpace(value); value != "" {
			out = append(out, value)
		}
	}
	return out
}

func boundedInt(raw string, fallback, minimum, maximum int) int {
	value, err := strconv.Atoi(raw)
	if err != nil {
		return fallback
	}
	if value < minimum {
		return minimum
	}
	if value > maximum {
		return maximum
	}
	return value
}
