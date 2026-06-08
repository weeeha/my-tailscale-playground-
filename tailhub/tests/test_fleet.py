from tailhub.fleet import Device, discover_fleet

STATUS = {
    "Self": {"HostName": "mac-studio", "DNSName": "mac-studio.tail.ts.net.",
             "TailscaleIPs": ["100.75.213.56", "fd7a::1"], "Online": True},
    "Peer": {
        "k1": {"HostName": "plantdashboard", "DNSName": "plantdashboard.tail.ts.net.",
               "TailscaleIPs": ["100.64.79.16"], "Online": True},
        "k2": {"HostName": "nick-iphone", "DNSName": "nick-iphone.tail.ts.net.",
               "TailscaleIPs": ["100.70.107.55"], "Online": False},
    },
}


def test_discover_fleet():
    devs = {d.host: d for d in discover_fleet(STATUS, probe_hosts={"plantdashboard", "fastclock"})}
    assert set(devs) == {"mac-studio", "plantdashboard", "nick-iphone"}

    pd = devs["plantdashboard"]
    assert pd == Device(host="plantdashboard", addr="100.64.79.16", online=True, has_probe=True)

    # iPhone: present, agentless (not in probe set), offline
    ip = devs["nick-iphone"]
    assert ip.addr == "100.70.107.55" and ip.online is False and ip.has_probe is False

    # Self is included but not a probe host here
    assert devs["mac-studio"].addr == "100.75.213.56" and devs["mac-studio"].has_probe is False


def test_handles_missing_fields():
    devs = discover_fleet({"Peer": {"k": {"HostName": "x", "TailscaleIPs": [], "Online": True}}},
                          probe_hosts=set())
    assert len(devs) == 1 and devs[0].addr == ""    # no IPv4 → empty addr, still listed
