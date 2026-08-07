// Copyright (c) Tailscale Inc & contributors
// SPDX-License-Identifier: BSD-3-Clause

// Command tailprobe serves one device's vitals over a Tailscale-only HTTP
// endpoint, reproducing the schema:1 JSON of tailtop/agent/fleet_collect.sh.
package main

import (
	"errors"
	"flag"
	"log"
	"net"
	"net/http"
	"os"
	"time"
)

// cgnat is Tailscale's 100.64.0.0/10 range.
var cgnat = func() *net.IPNet { _, n, _ := net.ParseCIDR("100.64.0.0/10"); return n }()

// pickTailscaleAddr returns the first IPv4 address inside 100.64.0.0/10.
func pickTailscaleAddr(addrs []net.Addr) (string, error) {
	for _, a := range addrs {
		var ip net.IP
		switch v := a.(type) {
		case *net.IPNet:
			ip = v.IP
		case *net.IPAddr:
			ip = v.IP
		}
		if ip4 := ip.To4(); ip4 != nil && cgnat.Contains(ip4) {
			return ip4.String(), nil
		}
	}
	return "", errors.New("no 100.64.0.0/10 (Tailscale) address found")
}

func resolveBindAddr(explicit string) (string, error) {
	if explicit != "" {
		return explicit, nil
	}
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return "", err
	}
	ip, err := pickTailscaleAddr(addrs)
	if err != nil {
		return "", err
	}
	return net.JoinHostPort(ip, "9100"), nil
}

// listenWithRetry retries listen until it succeeds or attempts is exhausted,
// returning the bound listener. At boot, binding the 100.x fails until
// tailscaled assigns it.
func listenWithRetry(addr string, attempts int, sleep func(), listen func(string) (net.Listener, error)) (net.Listener, error) {
	if attempts < 1 {
		attempts = 1
	}
	var last error
	for i := 0; i < attempts; i++ {
		ln, err := listen(addr)
		if err == nil {
			return ln, nil
		}
		last = err
		sleep()
	}
	return nil, last
}

func main() {
	addrFlag := flag.String("addr", "", "explicit bind address host:port (default: auto-detect 100.x:9100)")
	flag.Parse()

	addr, err := resolveBindAddr(*addrFlag)
	if err != nil {
		log.Fatalf("tailprobe: resolve bind addr: %v", err)
	}

	host, _ := os.Hostname()
	collect := func() (Vitals, error) {
		return Collect(os.DirFS("/"), Options{
			Host:     host,
			Kernel:   realKernel(),
			HomeRel:  "", // last_render disabled in Phase 0 unless configured
			Statfs:   realStatfs,
			Vcgencmd: realVcgencmd,
		})
	}
	srv := &http.Server{Handler: newMux(collect), ReadHeaderTimeout: 5 * time.Second}

	// Retry until tailscaled has assigned the address, then serve.
	ln, err := listenWithRetry(addr, 60, func() { time.Sleep(2 * time.Second) },
		func(a string) (net.Listener, error) { return net.Listen("tcp", a) })
	if err != nil {
		log.Fatalf("tailprobe: could not bind %s: %v", addr, err)
	}
	log.Printf("tailprobe: serving on %s", addr)
	log.Fatal(srv.Serve(ln))
}
