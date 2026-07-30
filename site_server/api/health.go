package handler

import "net/http"

// Health answers GET /api/health.
//
// The theme's `auto` backend probes this to decide whether a search server is
// answering at all, so it must fail when the index is missing rather than report
// a healthy backend with nothing behind it. The service returns 503 in that case.
func Health(w http.ResponseWriter, r *http.Request) {
	shared().Health(w, r)
}
