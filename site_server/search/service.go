// Package search answers the theme's search API from a Bluge index.
//
// It is deliberately free of process concerns: no flags, no log.Fatal, no
// listening. Two entry points wrap it — cmd/movenotes-site-server for a local
// process that also serves the static site, and api/ for Vercel functions, where
// the CDN serves the static site and only /api/* reaches Go code.
//
// The HTTP surface is the contract in the theme's
// assets/js/search/backends/bluge.js. The query grammar is parsed exactly once,
// client-side, so nothing here re-parses `tag:` prefixes or quotes.
package search

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sync"

	"github.com/blugelabs/bluge"
)

// Config locates the three things a search service needs. Empty fields are
// filled from the environment and then from defaults, so one binary works from a
// command line, from a shell profile, or from a serverless platform's project
// settings without any of them knowing about the others.
type Config struct {
	// IndexDir holds the Bluge index. It is only ever read by the service.
	IndexDir string
	// SourcePath is the JSONL obsidian2site.py writes. It is used to build the
	// index, never to answer a request.
	SourcePath string
	// SiteDir is the built Hugo output, for entry points that serve it.
	SiteDir string
}

const (
	// Defaults match the layout obsidian2site.py generates.
	DefaultIndexDir   = "server/bluge-index"
	DefaultSourcePath = "server/search-source.jsonl"
	DefaultSiteDir    = "public"

	EnvIndexDir   = "MOVENOTES_INDEX"
	EnvSourcePath = "MOVENOTES_SOURCE"
	EnvSiteDir    = "MOVENOTES_SITE"
)

// Resolve fills empty fields from the environment, then from the defaults.
// Explicit values always win, so a flag beats a deployment's env var.
func (c Config) Resolve() Config {
	c.IndexDir = firstNonEmpty(c.IndexDir, os.Getenv(EnvIndexDir), DefaultIndexDir)
	c.SourcePath = firstNonEmpty(c.SourcePath, os.Getenv(EnvSourcePath), DefaultSourcePath)
	c.SiteDir = firstNonEmpty(c.SiteDir, os.Getenv(EnvSiteDir), DefaultSiteDir)
	return c
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

// Service answers search requests from one Bluge index.
//
// The index is opened on first use rather than in the constructor: a serverless
// function is constructed on every cold start, and one that opened an index it
// might not be asked to search would pay for it on requests that never search.
// The reader is shared by every request the instance serves afterwards.
type Service struct {
	config Config
	once   sync.Once
	reader *bluge.Reader
	err    error
}

// New returns a service for cfg, resolving any empty fields.
func New(cfg Config) *Service {
	return &Service{config: cfg.Resolve()}
}

// Config returns the resolved configuration.
func (s *Service) Config() Config { return s.config }

// Close releases the index reader if it was ever opened. A long-running process
// should call it; a serverless function has nothing to close it for.
func (s *Service) Close() error {
	if s.reader == nil {
		return nil
	}
	return s.reader.Close()
}

// Reader opens the index once and returns the shared reader.
//
// It never builds. Indexing 100k notes takes minutes and needs a writable
// filesystem, so a request is the wrong place for it: an index that is missing is
// an operational error, reported as 503, not something to fix mid-request.
func (s *Service) Reader() (*bluge.Reader, error) {
	s.once.Do(func() {
		if info, err := os.Stat(s.config.IndexDir); err != nil || !info.IsDir() {
			s.err = fmt.Errorf(
				"no Bluge index at %q: build it before serving, with "+
					"'movenotes-site-server -index-only'", s.config.IndexDir)
			return
		}
		// Opening is read-only: verified against a directory with every write
		// permission removed, which is what a serverless filesystem looks like.
		s.reader, s.err = bluge.OpenReader(bluge.DefaultConfig(s.config.IndexDir))
		if s.err != nil {
			s.err = fmt.Errorf("open Bluge index %q: %w", s.config.IndexDir, s.err)
		}
	})
	return s.reader, s.err
}

// Notes returns the number of indexed notes.
func (s *Service) Notes() (uint64, error) {
	reader, err := s.Reader()
	if err != nil {
		return 0, err
	}
	return reader.Count()
}

// Health handles GET /api/health. The theme's auto backend reads the `backend`
// field to decide whether a server is answering at all, so an unavailable index
// must not answer 200.
func (s *Service) Health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("X-Movenotes-Search-Backend", "bluge")
	notes, err := s.Notes()
	if err != nil {
		unavailable(w, err)
		return
	}
	writeJSON(w, map[string]any{"backend": "bluge", "notes": notes})
	log.Printf("health remote=%s notes=%d", r.RemoteAddr, notes)
}

// unavailable reports a missing or unopenable index. 503, not 500: the request
// was fine, the deployment is not.
func unavailable(w http.ResponseWriter, err error) {
	log.Printf("search unavailable: %v", err)
	w.Header().Set("Cache-Control", "no-store")
	http.Error(w, "search index unavailable: "+err.Error(), http.StatusServiceUnavailable)
}

func writeJSON(w http.ResponseWriter, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	encoder := json.NewEncoder(w)
	encoder.SetEscapeHTML(true)
	if err := encoder.Encode(value); err != nil && !errors.Is(err, io.EOF) {
		log.Printf("write JSON: %v", err)
	}
}
