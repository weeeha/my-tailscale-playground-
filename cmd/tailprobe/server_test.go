// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func testMux() http.Handler {
	temp := 50.0
	return newMux(func() (Vitals, error) {
		return Vitals{Schema: 1, Host: "h", Thermal: Thermal{SoCTempC: &temp},
			SideThings: SideThings{Displays: []Display{}, USB: []string{}}}, nil
	})
}

func TestServerRoutes(t *testing.T) {
	mux := testMux()

	r := httptest.NewRecorder()
	mux.ServeHTTP(r, httptest.NewRequest("GET", "/healthz", nil))
	if r.Code != 200 || !strings.Contains(r.Body.String(), "ok") {
		t.Errorf("healthz: %d %q", r.Code, r.Body.String())
	}

	r = httptest.NewRecorder()
	mux.ServeHTTP(r, httptest.NewRequest("GET", "/vitals", nil))
	if r.Code != 200 || r.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("vitals: %d ct=%q", r.Code, r.Header().Get("Content-Type"))
	}
	var v Vitals
	if err := json.Unmarshal(r.Body.Bytes(), &v); err != nil || v.Schema != 1 {
		t.Errorf("vitals body: %v %s", err, r.Body.String())
	}

	r = httptest.NewRecorder()
	mux.ServeHTTP(r, httptest.NewRequest("GET", "/metrics", nil))
	if r.Code != 200 || !strings.Contains(r.Body.String(), "tailprobe_soc_temp_celsius") {
		t.Errorf("metrics: %d %q", r.Code, r.Body.String())
	}
}

func TestServerCollectError(t *testing.T) {
	mux := newMux(func() (Vitals, error) { return Vitals{}, errors.New("boom") })
	for _, path := range []string{"/vitals", "/metrics"} {
		r := httptest.NewRecorder()
		mux.ServeHTTP(r, httptest.NewRequest("GET", path, nil))
		if r.Code != 500 {
			t.Errorf("%s: got %d want 500", path, r.Code)
		}
	}
}
