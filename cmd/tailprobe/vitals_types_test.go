// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

package main

import (
	"encoding/json"
	"testing"
)

func TestVitalsMarshalsSchema1Shape(t *testing.T) {
	temp := 54.7
	running := true
	v := Vitals{
		Schema:      1,
		Host:        "fastclock",
		CollectedAt: "2026-06-07T00:24:42Z",
		Config:      Config{Model: "Raspberry Pi Zero 2 W", CPUCores: 4, MemTotalMB: 419},
		Thermal:     Thermal{SoCTempC: &temp, VcgencmdPresent: true},
		Health:      Health{Load1: 0.34, CPUPct: 17.4, UptimeS: 90432},
		SideThings:  SideThings{Displays: []Display{}, USB: []string{}, Battery: Battery{Present: false}},
		App:         App{Name: "superclock", Running: &running},
	}
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var got map[string]any
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	// schema:1 top-level keys the tailtop parser reads.
	for _, k := range []string{"schema", "host", "collected_at", "config", "thermal", "health", "side_things", "app"} {
		if _, ok := got[k]; !ok {
			t.Errorf("missing top-level key %q in %s", k, b)
		}
	}
	// nullable fields must be JSON null when nil, never omitted.
	none := Vitals{}
	b2, _ := json.Marshal(none)
	var got2 map[string]any
	_ = json.Unmarshal(b2, &got2)
	thermal := got2["thermal"].(map[string]any)
	if v, ok := thermal["soc_temp_c"]; !ok || v != nil {
		t.Errorf("soc_temp_c should be JSON null when unset, got %v (present=%v)", v, ok)
	}
}
