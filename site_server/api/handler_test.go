package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"movenotes/site-server/search"
)

// The serverless half is configured entirely from the environment, because a
// deployment has no command line. This exercises that path the way the platform
// does: env vars, no flags, one lazily opened index shared by both functions.
//
// It cannot test Vercel itself. What it can test is that these two exported
// functions answer correctly given only environment configuration, which is the
// part that would otherwise be discovered broken after a deploy.
func TestFunctionsAnswerFromEnvironmentConfiguration(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "search-source.jsonl")
	records := strings.Join([]string{
		`{"id":0,"url":"/notes/a.html","title":"First","date":"2026-07-01T00:00:00Z","body":"canadian housing","category":"Notes","tags":["canada"],"displayTags":["canada"],"readingTime":2}`,
		`{"id":1,"url":"/notes/b.html","title":"Second","date":"2026-06-01T00:00:00Z","body":"video codecs","category":"Notes","tags":["codec"],"displayTags":["codec"],"readingTime":1}`,
	}, "\n") + "\n"
	if err := os.WriteFile(source, []byte(records), 0o644); err != nil {
		t.Fatal(err)
	}
	index := filepath.Join(root, "index")
	// Built here, not by the function: a serverless filesystem is read-only and
	// indexing takes minutes on a real archive.
	if err := search.BuildIndex(source, index); err != nil {
		t.Fatal(err)
	}

	t.Setenv(search.EnvIndexDir, index)
	t.Setenv(search.EnvSourcePath, source)

	health := httptest.NewRecorder()
	Health(health, httptest.NewRequest(http.MethodGet, "/api/health", nil))
	if health.Code != http.StatusOK {
		t.Fatalf("health status = %d: %s", health.Code, health.Body.String())
	}
	var probe struct {
		Backend string `json:"backend"`
		Notes   int    `json:"notes"`
	}
	if err := json.Unmarshal(health.Body.Bytes(), &probe); err != nil {
		t.Fatal(err)
	}
	// The theme's auto backend requires the backend to name itself here.
	if probe.Backend != "bluge" || probe.Notes != 2 {
		t.Errorf("health = %+v", probe)
	}

	results := httptest.NewRecorder()
	Search(results, httptest.NewRequest(http.MethodGet, "/api/search?tag=codec", nil))
	if results.Code != http.StatusOK {
		t.Fatalf("search status = %d: %s", results.Code, results.Body.String())
	}
	var response struct {
		Total   int `json:"total"`
		Results []struct {
			URL  string `json:"url"`
			Date string `json:"date"`
		} `json:"results"`
	}
	if err := json.Unmarshal(results.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if response.Total != 1 || response.Results[0].URL != "/notes/b.html" {
		t.Errorf("search response = %+v", response)
	}
	if response.Results[0].Date != "2026-06-01" {
		t.Errorf("date = %q, want the contract's YYYY-MM-DD", response.Results[0].Date)
	}

	// Both functions share one service, so the index is opened once per instance
	// however many routes are hit.
	if shared() != shared() {
		t.Error("each call built a new service; the reader must be shared")
	}
}
