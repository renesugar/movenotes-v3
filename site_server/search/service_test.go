package search

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
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

// TestURLsInBodyAreSearchable is the step-38 regression test: the queries a user
// ran against a real 166,654-note archive, all of which returned nothing because
// the generator deleted every URL before indexing it. See step 37 in
// LEDGER_MIGRATION_PLAN.md.
//
// The bodies here are what the fixed generator emits — prose, then the note's
// links appended. Nothing about the query side changed; Bluge's standard
// analyser already tokenised URLs well, keeping the host whole and splitting the
// path into words. That is what makes searching by component work.
func TestURLsInBodyAreSearchable(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "search-source.jsonl")
	records := []string{
		`{"id":0,"url":"/notes/housing.html","title":"@JohnPasalis legalize housing","date":"2026-07-02T00:00:00Z",` +
			`"body":"three million more canadians in housing need than cmhc estimates suggest report ` +
			`https://x.com/i/web/status/1720100485901000962 ` +
			`https://globalnews.ca/news/10063968/more-canadians-housing-need-cmhc-estimates-report/",` +
			`"summary":"three million more canadians","category":"Twitter","tags":["vanre"],"displayTags":["vanre"],"readingTime":1}`,
		`{"id":1,"url":"/notes/links.html","title":"Assorted links","date":"2026-07-01T00:00:00Z",` +
			`"body":"pizza vs any celebrity ` +
			`https://open.spotify.com/episode/6zDxDPCr8wiiJKmbxa7HmP?si=p_kKyulrRcSakJybqvornQ&nd=1&dlsi=17a6dea183df4c83 ` +
			`http://www.upworthy.com/a-12-year-old-egyptian-boy-flabbergasts-an-interviewer-they-werent-expecting-a-political-genius-4?g=2 ` +
			`http://t.co/CT… ` +
			`https://www.imf.org/external/pubs/ft/fandd/2019/09/the-rise-of-phantom-FDI-in-tax-havens-damgaard.htm ` +
			`https://trends.google.com/trends/explore?q=%2Fm%2F0gs6vr,pizza",` +
			`"summary":"pizza vs any celebrity","category":"Twitter","tags":["cdnpoli"],"displayTags":["cdnpoli"],"readingTime":1}`,
		`{"id":2,"url":"/notes/plain.html","title":"No links here","date":"2026-06-01T00:00:00Z",` +
			`"body":"housing and pizza, but nothing to click","summary":"no links","category":"Notes","tags":[],"displayTags":[],"readingTime":1}`,
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

	for _, c := range []struct {
		name   string
		values url.Values
		want   []string
	}{
		{"whole url", url.Values{"q": {"https://globalnews.ca/news/10063968/more-canadians-housing-need-cmhc-estimates-report/"}}, []string{"/notes/housing.html"}},
		{"url without the scheme", url.Values{"q": {"globalnews.ca/news/10063968/more-canadians-housing-need-cmhc-estimates-report/"}}, []string{"/notes/housing.html"}},
		{"path segment and the rest", url.Values{"q": {"10063968/more-canadians-housing-need-cmhc-estimates-report/"}}, []string{"/notes/housing.html"}},
		{"url as a quoted phrase", url.Values{"phrase": {"https://globalnews.ca/news/10063968/more-canadians-housing-need-cmhc-estimates-report/"}}, []string{"/notes/housing.html"}},
		{"components, space separated", url.Values{"q": {"globalnews.ca news"}}, []string{"/notes/housing.html"}},
		{"url prefix", url.Values{"q": {"https://globalnews.ca/news/"}}, []string{"/notes/housing.html"}},
		{"x.com permalink", url.Values{"q": {"https://x.com/i/web/status/1720100485901000962"}}, []string{"/notes/housing.html"}},
		{"tag and url together", url.Values{"tag": {"vanre"}, "q": {"https://x.com/i/web/status/1720100485901000962"}}, []string{"/notes/housing.html"}},
		{"prose word and url together", url.Values{"q": {"housing https://globalnews.ca/news/"}}, []string{"/notes/housing.html"}},
		{"query string with ampersands", url.Values{"q": {"https://open.spotify.com/episode/6zDxDPCr8wiiJKmbxa7HmP?si=p_kKyulrRcSakJybqvornQ&nd=1&dlsi=17a6dea183df4c83"}}, []string{"/notes/links.html"}},
		{"percent escapes", url.Values{"q": {"https://trends.google.com/trends/explore?q=%2Fm%2F0gs6vr,pizza"}}, []string{"/notes/links.html"}},
		{"url with a trailing query flag", url.Values{"q": {"http://www.upworthy.com/a-12-year-old-egyptian-boy-flabbergasts-an-interviewer-they-werent-expecting-a-political-genius-4?g=2"}}, []string{"/notes/links.html"}},
		{"truncated t.co link", url.Values{"q": {"http://t.co/CT…"}}, []string{"/notes/links.html"}},
		{"imf article", url.Values{"q": {"https://www.imf.org/external/pubs/ft/fandd/2019/09/the-rise-of-phantom-FDI-in-tax-havens-damgaard.htm"}}, []string{"/notes/links.html"}},
		// A host is a term like any other, so it selects only the notes linking it.
		{"host alone", url.Values{"q": {"t.co"}}, []string{"/notes/links.html"}},
		// The note that links nothing is still found by its prose, and never by a link.
		{"prose still matches the linkless note", url.Values{"q": {"click"}}, []string{"/notes/plain.html"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			service.Search(recorder, httptest.NewRequest(
				http.MethodGet, "/api/search?"+c.values.Encode(), nil))
			if recorder.Code != http.StatusOK {
				t.Fatalf("status = %d: %s", recorder.Code, recorder.Body.String())
			}
			var got struct {
				Total   int `json:"total"`
				Results []struct {
					URL string `json:"url"`
				} `json:"results"`
			}
			if err := json.Unmarshal(recorder.Body.Bytes(), &got); err != nil {
				t.Fatalf("decode: %v", err)
			}
			var urls []string
			for _, r := range got.Results {
				urls = append(urls, r.URL)
			}
			if got.Total != len(c.want) || !reflect.DeepEqual(urls, c.want) {
				t.Errorf("total = %d, results = %q; want %q", got.Total, urls, c.want)
			}
		})
	}
}
