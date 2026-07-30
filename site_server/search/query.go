package search

import (
	"encoding/json"
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
	ID       int    `json:"id"`
	URL      string `json:"url"`
	Title    string `json:"title"`
	Date     string `json:"date"`
	Body     string `json:"body"`
	Summary  string `json:"summary"`
	Category string `json:"category"`
	// Tags are the tags written in the note, uncapped: what `tag:` matches and
	// what a result card shows. It used to carry every generated content word
	// as well, which made `tag:` answer differently from the tag archive and
	// from Pagefind for the same query — see step 46. Generated words are still
	// found by free text, being words of the note.
	Tags        []string `json:"tags"`
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
//
// `expr` carries the expression tree when the caller sends one, and then it is
// the whole query — the flat fields below cannot express `OR`, negation or
// grouping. They remain for callers that have no tree: the `offset`/`limit`
// callers the contract promises, and any adapter not yet updated.
type searchParams struct {
	expr       *exprNode
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

// exprNode is one node of the parsed query, mirroring the tree that
// assets/js/search/query.js builds. The shapes are:
//
//	{"type":"and","nodes":[…]}     {"type":"or","nodes":[…]}
//	{"type":"not","node":{…}}      {"type":"term","value":"cat"}
//	{"type":"phrase","value":"…"}  {"type":"field","field":"tag","value":"x"}
//
// Field names are the grammar's: category, tag, since, until.
type exprNode struct {
	Type  string      `json:"type"`
	Nodes []*exprNode `json:"nodes,omitempty"`
	Node  *exprNode   `json:"node,omitempty"`
	Field string      `json:"field,omitempty"`
	Value string      `json:"value,omitempty"`
}

// maxExprBytes bounds the tree a request may carry. A hand-typed query is a few
// hundred bytes; this is room to spare without letting a URL become a denial of
// service.
const maxExprBytes = 8 << 10

// maxExprDepth bounds nesting, so a crafted tree cannot recurse the builder
// into a stack overflow.
const maxExprDepth = 32

func parseExpr(raw string) (*exprNode, error) {
	if strings.TrimSpace(raw) == "" {
		return nil, nil
	}
	if len(raw) > maxExprBytes {
		return nil, fmt.Errorf("expr: larger than %d bytes", maxExprBytes)
	}
	var node exprNode
	if err := json.Unmarshal([]byte(raw), &node); err != nil {
		return nil, errors.New("expr: not valid JSON")
	}
	if err := validateExpr(&node, 0); err != nil {
		return nil, err
	}
	return &node, nil
}

func validateExpr(node *exprNode, depth int) error {
	if node == nil {
		return errors.New("expr: empty node")
	}
	if depth > maxExprDepth {
		return fmt.Errorf("expr: nested deeper than %d", maxExprDepth)
	}
	switch node.Type {
	case "and", "or":
		if len(node.Nodes) == 0 {
			return fmt.Errorf("expr: %s with no operands", node.Type)
		}
		for _, child := range node.Nodes {
			if err := validateExpr(child, depth+1); err != nil {
				return err
			}
		}
	case "not":
		return validateExpr(node.Node, depth+1)
	case "term", "phrase":
		if node.Value == "" {
			return fmt.Errorf("expr: %s with no value", node.Type)
		}
	case "field":
		switch node.Field {
		case "category", "tag", "since", "until":
		default:
			return fmt.Errorf("expr: unknown field %q", node.Field)
		}
		if node.Value == "" {
			return errors.New("expr: field with no value")
		}
		if node.Field == "since" || node.Field == "until" {
			if _, err := time.Parse(dateLayout, node.Value); err != nil {
				return fmt.Errorf("%s: expected YYYY-MM-DD", node.Field)
			}
		}
	default:
		return fmt.Errorf("expr: unknown node type %q", node.Type)
	}
	return nil
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
	expr, err := parseExpr(values.Get("expr"))
	if err != nil {
		return searchParams{}, err
	}
	params := searchParams{
		expr:       expr,
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

// buildQuery turns the parsed query into one Bluge query. A caller that sent an
// expression tree gets that; otherwise the flat fields are ANDed as they always
// were. Either way a term matches the title, the summary or the body, with the
// title weighted highest.
func buildQuery(params searchParams) bluge.Query {
	if params.expr != nil {
		if query := buildExpr(params.expr); query != nil {
			return query
		}
		return bluge.NewMatchAllQuery()
	}
	return buildFlatQuery(params)
}

// buildExpr walks the tree. Bluge has no standalone negation — it is a clause of
// a boolean query — so a `not` is only ever built as the MustNot of the boolean
// that contains it, which is why the and/or cases handle their negated children
// rather than recursing blindly.
func buildExpr(node *exprNode) bluge.Query {
	switch node.Type {
	case "and":
		boolean := bluge.NewBooleanQuery()
		positives := 0
		for _, child := range node.Nodes {
			if child.Type == "not" {
				if inner := buildExpr(child.Node); inner != nil {
					boolean.AddMustNot(inner)
				}
				continue
			}
			if query := buildExpr(child); query != nil {
				boolean.AddMust(query)
				positives++
			}
		}
		// `-a -b` with nothing positive is every note except those: Bluge
		// answers a MustNot-only boolean directly, no match-all needed.
		_ = positives
		return boolean

	case "or":
		boolean := bluge.NewBooleanQuery().SetMinShould(1)
		for _, child := range node.Nodes {
			// A negated branch needs no special handling here: the `not` case
			// below already builds "everything without this", which is exactly
			// what `a OR -b` asks that branch to contribute. Wrapping it again
			// in a match-all-minus is a double negation, and reads as `a OR b`.
			if query := buildExpr(child); query != nil {
				boolean.AddShould(query)
			}
		}
		return boolean

	case "not":
		// Only reached when a negation is the whole query.
		if inner := buildExpr(node.Node); inner != nil {
			return bluge.NewBooleanQuery().AddMustNot(inner)
		}
		return nil

	case "term":
		// The same "title, summary or body, title weighted highest" shape the
		// flat path uses, one tree leaf at a time.
		return bluge.NewBooleanQuery().SetMinShould(1).AddShould(
			bluge.NewMatchQuery(node.Value).SetField("title").
				SetOperator(bluge.MatchQueryOperatorAnd).SetBoost(4),
			bluge.NewMatchQuery(node.Value).SetField("summary").
				SetOperator(bluge.MatchQueryOperatorAnd).SetBoost(2),
			bluge.NewMatchQuery(node.Value).SetField("body").
				SetOperator(bluge.MatchQueryOperatorAnd),
		)

	case "phrase":
		return bluge.NewBooleanQuery().SetMinShould(1).AddShould(
			bluge.NewMatchPhraseQuery(node.Value).SetField("title").SetBoost(4),
			bluge.NewMatchPhraseQuery(node.Value).SetField("summary").SetBoost(2),
			bluge.NewMatchPhraseQuery(node.Value).SetField("body"),
		)

	case "field":
		switch node.Field {
		case "category":
			return bluge.NewTermQuery(node.Value).SetField("category")
		case "tag":
			return bluge.NewTermQuery(strings.ToLower(node.Value)).SetField("tag")
		case "since":
			bound, err := time.Parse(dateLayout, node.Value)
			if err != nil {
				return nil
			}
			return bluge.NewDateRangeInclusiveQuery(bound.UTC(), time.Time{}, true, false).
				SetField("date")
		case "until":
			bound, err := time.Parse(dateLayout, node.Value)
			if err != nil {
				return nil
			}
			return bluge.NewDateRangeInclusiveQuery(time.Time{}, bound.UTC(), true, false).
				SetField("date")
		}
	}
	return nil
}

func buildFlatQuery(params searchParams) bluge.Query {
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
// log line. The client sends structure, not text, so this renders it back —
// which also makes the log show how the query was *understood*, not just what
// was typed.
func describe(params searchParams) string {
	if params.expr != nil {
		return describeExpr(params.expr, false)
	}
	return describeFlat(params)
}

// describeExpr renders a node in the grammar's own syntax. `group` asks for
// parentheses when the context binds tighter than the node does.
func describeExpr(node *exprNode, group bool) string {
	switch node.Type {
	case "and":
		parts := make([]string, 0, len(node.Nodes))
		for _, child := range node.Nodes {
			// An OR inside an AND needs brackets; AND inside OR does not,
			// because AND already binds tighter.
			parts = append(parts, describeExpr(child, child.Type == "or"))
		}
		return maybeGroup(strings.Join(parts, " "), group)
	case "or":
		parts := make([]string, 0, len(node.Nodes))
		for _, child := range node.Nodes {
			parts = append(parts, describeExpr(child, false))
		}
		return maybeGroup(strings.Join(parts, " OR "), group)
	case "not":
		return "-" + describeExpr(node.Node, node.Node.Type == "and" || node.Node.Type == "or")
	case "phrase":
		return strconv.Quote(node.Value)
	case "field":
		return clause(node.Field, node.Value)
	}
	return node.Value
}

func maybeGroup(text string, group bool) string {
	if group {
		return "(" + text + ")"
	}
	return text
}

func describeFlat(params searchParams) string {
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
