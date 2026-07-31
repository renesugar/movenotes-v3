// Package handler is the serverless half of the server: one exported
// http.HandlerFunc per file, which is what Vercel's Go runtime turns into a
// function. The CDN serves the built site, so nothing here touches static files.
//
// Each function gets its own process, so each opens the index itself — lazily, on
// the first request that needs it, and then shares the reader for the life of the
// instance. The index must already exist: it is read-only here, and a serverless
// filesystem is read-only anyway. Opening a Bluge index without write access is
// verified behaviour, not an assumption.
//
// Configuration comes from the environment — MOVENOTES_INDEX and
// MOVENOTES_SOURCE — because a deployment has no command line.
package handler

import (
	"net/http"
	"sync"

	"movenotes/site-server/search"
)

var (
	once    sync.Once
	service *search.Service
)

// shared returns the per-instance service. The reader inside it is opened on
// first search, so a cold start that is never asked to search pays nothing.
func shared() *search.Service {
	once.Do(func() { service = search.New(search.Config{}) })
	return service
}

// Search answers GET /api/search.
func Search(w http.ResponseWriter, r *http.Request) {
	shared().Search(w, r)
}
