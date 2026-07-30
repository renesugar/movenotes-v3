package search

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestConfigResolutionOrder(t *testing.T) {
	t.Setenv(EnvIndexDir, "/from/env/index")
	t.Setenv(EnvSourcePath, "/from/env/source.jsonl")
	t.Setenv(EnvSiteDir, "/from/env/public")

	// An explicit value wins over the environment: a flag has to beat a
	// deployment's project settings, not the other way round.
	explicit := Config{IndexDir: "/explicit/index"}.Resolve()
	if explicit.IndexDir != "/explicit/index" {
		t.Errorf("IndexDir = %q, want the explicit value", explicit.IndexDir)
	}
	if explicit.SourcePath != "/from/env/source.jsonl" {
		t.Errorf("SourcePath = %q, want the environment value", explicit.SourcePath)
	}

	os.Unsetenv(EnvIndexDir)
	os.Unsetenv(EnvSourcePath)
	os.Unsetenv(EnvSiteDir)
	fallback := Config{}.Resolve()
	if fallback.IndexDir != DefaultIndexDir || fallback.SourcePath != DefaultSourcePath ||
		fallback.SiteDir != DefaultSiteDir {
		t.Errorf("defaults = %+v", fallback)
	}
}

// A deployment whose index was never built must say so, and must not report a
// healthy backend: the theme's auto backend reads /api/health to decide whether a
// server is answering, and would otherwise choose Bluge and then fail every query.
func TestMissingIndexIsUnavailableNotHealthy(t *testing.T) {
	service := New(Config{IndexDir: filepath.Join(t.TempDir(), "absent")})

	for path, handler := range map[string]http.HandlerFunc{
		"/api/health": service.Health,
		"/api/search": service.Search,
	} {
		recorder := httptest.NewRecorder()
		handler(recorder, httptest.NewRequest(http.MethodGet, path, nil))
		if recorder.Code != http.StatusServiceUnavailable {
			t.Errorf("%s status = %d, want 503", path, recorder.Code)
		}
		if !strings.Contains(recorder.Body.String(), "index-only") {
			t.Errorf("%s body does not say how to fix it: %q", path, recorder.Body.String())
		}
	}
}

// The handlers must never build an index: it takes minutes on a real archive and
// needs a writable filesystem, neither of which a request has.
func TestRequestsNeverBuildAnIndex(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "search-source.jsonl")
	if err := os.WriteFile(source, []byte(`{"id":0,"url":"/n.html","title":"N","body":"b"}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	index := filepath.Join(root, "index")
	service := New(Config{SourcePath: source, IndexDir: index})

	recorder := httptest.NewRecorder()
	service.Search(recorder, httptest.NewRequest(http.MethodGet, "/api/search?q=b", nil))
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", recorder.Code)
	}
	if _, err := os.Stat(index); !os.IsNotExist(err) {
		t.Fatalf("the request created %s; handlers must never build", index)
	}
}

func TestSearchOverABuiltIndex(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "search-source.jsonl")
	records := []string{
		`{"id":0,"url":"/notes/a.html","title":"Bank of Canada rate note","date":"2026-07-01T00:00:00Z","body":"the interest rate decision and canadian housing","summary":"rates","category":"Notes","tags":["canada","economics"],"displayTags":["canada","economics"],"readingTime":3}`,
		`{"id":1,"url":"/notes/b.html","title":"Codec note","date":"2026-06-15T00:00:00Z","body":"video codecs and the av1 codec","summary":"codecs","category":"Notes","tags":["codec"],"displayTags":["codec"],"readingTime":1}`,
	}
	if err := os.WriteFile(source, []byte(strings.Join(records, "\n")+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	index := filepath.Join(root, "index")
	if err := BuildIndex(source, index); err != nil {
		t.Fatalf("BuildIndex: %v", err)
	}

	service := New(Config{SourcePath: source, IndexDir: index})
	defer service.Close()

	if notes, err := service.Notes(); err != nil || notes != 2 {
		t.Fatalf("Notes() = %d, %v; want 2", notes, err)
	}

	type result struct {
		URL         string   `json:"url"`
		Title       string   `json:"title"`
		Category    string   `json:"category"`
		Tags        []string `json:"tags"`
		Date        string   `json:"date"`
		ReadingTime int      `json:"readingTime"`
	}
	type response struct {
		Backend string   `json:"backend"`
		Query   string   `json:"query"`
		Total   int      `json:"total"`
		Page    int      `json:"page"`
		Per     int      `json:"per"`
		Results []result `json:"results"`
	}

	for _, c := range []struct {
		name  string
		query string
		total int
		first string
	}{
		{"tag", "tag=codec", 1, "/notes/b.html"},
		{"category and tag", "category=Notes&tag=canada", 1, "/notes/a.html"},
		{"phrase", "phrase=interest+rate", 1, "/notes/a.html"},
		{"free terms", "q=canadian+housing", 1, "/notes/a.html"},
		{"date window", "since=2026-06-01&until=2026-07-01", 1, "/notes/b.html"},
		{"match all is newest first", "", 2, "/notes/a.html"},
		{"generated word tag", "q=codecs", 1, "/notes/b.html"},
	} {
		t.Run(c.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			service.Search(recorder, httptest.NewRequest(http.MethodGet, "/api/search?"+c.query, nil))
			if recorder.Code != http.StatusOK {
				t.Fatalf("status = %d: %s", recorder.Code, recorder.Body.String())
			}
			var got response
			if err := json.Unmarshal(recorder.Body.Bytes(), &got); err != nil {
				t.Fatalf("decode: %v", err)
			}
			if got.Backend != "bluge" {
				t.Errorf("backend = %q", got.Backend)
			}
			if got.Total != c.total {
				t.Errorf("total = %d, want %d (query %q)", got.Total, c.total, got.Query)
			}
			if c.total > 0 && got.Results[0].URL != c.first {
				t.Errorf("first result = %q, want %q", got.Results[0].URL, c.first)
			}
			if recorder.Header().Get("Server-Timing") == "" {
				t.Error("no Server-Timing header")
			}
		})
	}

	// A result card renders straight from these fields, so the date is the
	// contract's YYYY-MM-DD and not the note's full timestamp.
	recorder := httptest.NewRecorder()
	service.Search(recorder, httptest.NewRequest(http.MethodGet, "/api/search?tag=codec", nil))
	var got response
	if err := json.Unmarshal(recorder.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	first := got.Results[0]
	if first.Date != "2026-06-15" {
		t.Errorf("date = %q, want 2026-06-15", first.Date)
	}
	if first.Category != "Notes" || first.ReadingTime != 1 || first.Title != "Codec note" {
		t.Errorf("result = %+v", first)
	}
	// A card shows the tags written in the note, not the generated content
	// words: `tag:` matches all of them, but only these are stored.
	if len(first.Tags) != 1 || first.Tags[0] != "codec" {
		t.Errorf("tags = %q", first.Tags)
	}

	// Health only answers when there is really an index behind it.
	recorder = httptest.NewRecorder()
	service.Health(recorder, httptest.NewRequest(http.MethodGet, "/api/health", nil))
	if recorder.Code != http.StatusOK ||
		!strings.Contains(recorder.Body.String(), `"notes":2`) {
		t.Errorf("health = %d %q", recorder.Code, recorder.Body.String())
	}
}

// The index is opened read-only. Verified against a directory with every write
// permission removed, which is what a serverless filesystem looks like — the
// whole api/ half depends on this being true.
func TestOpensAReadOnlyIndexDirectory(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "search-source.jsonl")
	if err := os.WriteFile(source,
		[]byte(`{"id":0,"url":"/n.html","title":"Note","date":"2026-07-01T00:00:00Z","body":"body text"}`+"\n"),
		0o644); err != nil {
		t.Fatal(err)
	}
	index := filepath.Join(root, "index")
	if err := BuildIndex(source, index); err != nil {
		t.Fatal(err)
	}

	entries, err := os.ReadDir(index)
	if err != nil {
		t.Fatal(err)
	}
	before := len(entries)
	for _, entry := range entries {
		if err := os.Chmod(filepath.Join(index, entry.Name()), 0o444); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Chmod(index, 0o555); err != nil {
		t.Fatal(err)
	}
	// Restore write permission so t.TempDir cleanup can remove it.
	defer func() {
		os.Chmod(index, 0o755)
		for _, entry := range entries {
			os.Chmod(filepath.Join(index, entry.Name()), 0o644)
		}
	}()

	service := New(Config{SourcePath: source, IndexDir: index})
	defer service.Close()
	recorder := httptest.NewRecorder()
	service.Search(recorder, httptest.NewRequest(http.MethodGet, "/api/search?q=body", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("read-only index: status = %d: %s", recorder.Code, recorder.Body.String())
	}
	if after, _ := os.ReadDir(index); len(after) != before {
		t.Errorf("opening the index changed its contents: %d files, was %d", len(after), before)
	}
}
