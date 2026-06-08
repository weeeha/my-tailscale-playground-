// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

// Package main — HTTP mux for /healthz, /vitals, /metrics.
package main

import (
	"encoding/json"
	"net/http"
)

// newMux builds the probe's HTTP routes. collect is called per request.
func newMux(collect func() (Vitals, error)) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		_, _ = w.Write([]byte("ok\n"))
	})

	mux.HandleFunc("/vitals", func(w http.ResponseWriter, r *http.Request) {
		v, err := collect()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		enc := json.NewEncoder(w)
		enc.SetEscapeHTML(false)
		_ = enc.Encode(v)
	})

	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		v, err := collect()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		WritePrometheus(w, v)
	})

	return mux
}
