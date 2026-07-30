package search

import (
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/blugelabs/bluge"
)

// Search handles GET /api/search. See search-source.jsonl for what is indexed
// and the theme's bluge.js for the response shape.
func (s *Service) Search(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	w.Header().Set("X-Movenotes-Search-Backend", "bluge")
	if r.Method != http.MethodGet {
		http.Error(w, "GET required", http.StatusMethodNotAllowed)
		return
	}
	params, err := parseParams(r.URL.Query())
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	reader, err := s.Reader()
	if err != nil {
		unavailable(w, err)
		return
	}

	// Ask for exactly the window this page needs. Bluge ranks the whole match
	// set but materialises only offset+per documents, which is what keeps
	// response time flat as the archive grows.
	request := bluge.NewTopNSearch(params.per, buildQuery(params)).
		SetFrom(params.offset).
		WithStandardAggregations()
	if params.sortByDate {
		request.SortBy([]string{"-date", "-_score"})
	}
	iterator, err := reader.Search(r.Context(), request)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	described := describe(params)
	response := searchResponse{
		Backend: "bluge",
		Query:   described,
		Page:    params.page,
		Per:     params.per,
		Offset:  params.offset,
		Limit:   params.per,
		Results: make([]searchResult, 0, params.per),
	}
	if aggregations := iterator.Aggregations(); aggregations != nil {
		response.Total = aggregations.Count()
	}
	for {
		match, err := iterator.Next()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		if match == nil {
			break
		}
		result, err := toResult(match)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		response.Results = append(response.Results, result)
	}

	elapsed := time.Since(started)
	w.Header().Set("Server-Timing", fmt.Sprintf("search;dur=%.3f", float64(elapsed.Microseconds())/1000.0))
	writeJSON(w, response)
	// One line per request, so a site that looks like it is not reaching the
	// backend can be told apart from one that is and found nothing.
	log.Printf("search remote=%s query=%q total=%d offset=%d per=%d returned=%d duration=%s",
		r.RemoteAddr, described, response.Total, params.offset, params.per,
		len(response.Results), elapsed.Round(time.Millisecond))
}

// Mux returns the API routes, without any static file serving. Both entry points
// mount the same two paths, so a route added here reaches local and deployed
// alike.
func (s *Service) Mux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/health", s.Health)
	mux.HandleFunc("/api/search", s.Search)
	return mux
}
