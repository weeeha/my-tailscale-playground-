# Mac ↔ Windows File Sharing over Tailscale

End-to-end recipe for mounting Windows drives in macOS Finder (and Mac home folders in Windows Explorer) over Tailscale — works anywhere in the world with zero router/firewall config.

## What you get

- Native SMB mounts in Finder and Explorer
- Same URLs work on home Wi-Fi, café Wi-Fi, cellular, abroad
- Encrypted by Tailscale (WireGuard) end-to-end
- Mobile access too (iOS Files app, Android via VLC/Solid Explorer)

## Prerequisites

- Tailscale installed and signed in on both machines, both showing in `tailscale status`
- SSH access to the Windows machine (used here for setup; not required for ongoing use)
- macOS with admin sudo
- Windows 10/11 with admin rights

## Architecture

```
[Mac]  --SMB over Tailscale (utun)-->  [Windows PC]
   ↑                                        ↑
   |                                        |
   +-- smbd (file sharing on)               +-- LanmanServer + named shares
   +-- nickv share = /Users/nickv               +-- LocalAccountTokenFilterPolicy = 1
                                                +-- dedicated local admin (not MSA)
```

---

## Step 1 — Confirm Tailscale is up on both ends

On Mac:

```bash
tailscale status
```

Note your PC's Tailscale IP (`100.x.x.x`) and its MagicDNS hostname (the short name in the second column).

Test reachability of SMB port 445:

```bash
nc -zv -w 3 <PC_HOSTNAME> 445
```

If `Connection succeeded` you're good.

---

## Step 2 — Enable SMB on the Mac (host home folder)

By default `smbd` is **off** even when you've added share points via System Settings. Enable it and add your home folder as a share:

```bash
sudo launchctl enable system/com.apple.smbd
sudo launchctl kickstart -k system/com.apple.smbd
sudo sharing -a /Users/<YOUR_MAC_USERNAME> -n "<YOUR_MAC_USERNAME>" -s 001
```

The `-s 001` flag = SMB only (no legacy AFP/FTP).

Verify:

```bash
pgrep -lf smbd                     # smbd should appear
sharing -l | grep -A 1 <YOUR_MAC_USERNAME>
```

From Windows, mount via:

```
\\<MAC_HOSTNAME>\<YOUR_MAC_USERNAME>
```

Username = your Mac login name, password = your **local Mac password** (Apple ID password does **not** work for SMB).

---

## Step 3 — Create a dedicated local admin on Windows

### Why not just use your Microsoft Account?

If you sign into Windows with a Microsoft Account (MSA):

- The "username" for SMB is your MSA email (`you@outlook.com`), not the short local name
- The password is your **MSA password** (the one for login.live.com) — **not** your Windows Hello PIN
- Rotating it touches your entire Microsoft identity

A dedicated **local admin account** is cleaner:

- Real username/password under your control
- Same creds work for SSH and SMB
- Easy to revoke or rotate without touching your main login

### Create it

From a Mac terminal (SSH'd into the Windows box) or directly in PowerShell on Windows:

```powershell
$pw = Read-Host -AsSecureString "New password for the remote account"
New-LocalUser -Name 'remoteadmin' -Password $pw `
    -FullName 'Remote Admin' `
    -Description 'SSH+SMB access' `
    -PasswordNeverExpires -AccountNeverExpires
Add-LocalGroupMember -Group 'Administrators' -Member 'remoteadmin'
```

### Authorize your SSH key (if you want key-based SSH)

Windows OpenSSH stores **admin** users' authorized keys in a shared file:

```
C:\ProgramData\ssh\administrators_authorized_keys
```

Append your `~/.ssh/id_ed25519.pub` to that file. ACLs must be SYSTEM + Administrators full control only — the default `sshd_config` enforces this.

---

## Step 4 — Allow local admins to access admin shares (CRITICAL)

This is the **most common gotcha**. By default Windows strips the admin token from network logons by **local** accounts. Symptoms: SMB auth succeeds (`smbutil view` works) but mounting `C$`/`G$`/`ADMIN$` returns `Input/output error` or "There was a problem connecting to the server."

Fix it once:

```cmd
reg add HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System ^
    /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f
```

Then restart the SMB server service (no reboot needed):

```powershell
Restart-Service -Name LanmanServer -Force
```

**Security note:** this reverts to pre-Vista behavior, trusting network logons by local admins with full token. Acceptable on a private Tailscale-only network with a unique strong password. **Do not** apply on a domain machine you don't own.

---

## Step 5 — Use named shares for folders with NTFS junctions

`C$` exposes the raw NTFS tree, which includes Windows' legacy compatibility junctions (`Application Data`, `My Documents`, `NetHood`, etc.) inside every user profile, plus any junctions you've created (e.g. for OneDrive, or for redirecting paths to a secondary drive).

macOS SMB cannot traverse these reparse points — listing a directory that contains one aborts with `fts_read: Invalid argument`. So:

- ✅ **Browsing `C$` root in Finder** — works
- ❌ **Descending into `C:\Users\<name>`** — fails on the first junction
- ❌ **Some deep paths in `Program Files (x86)`** — fail on Common Files junction
- ✅ **`G$` or other drives without junctions** — work perfectly

### Solution: create dedicated SMB shares rooted at the actual folder you want

```powershell
New-SmbShare -Name 'models' `
    -Path 'C:\Users\<USERNAME>\models' `
    -FullAccess 'remoteadmin' `
    -Description 'AI model files'

New-SmbShare -Name 'desktop' `
    -Path 'C:\Users\<USERNAME>\Desktop' `
    -FullAccess 'remoteadmin'

New-SmbShare -Name 'onedrive' `
    -Path 'C:\Users\<USERNAME>\OneDrive' `
    -FullAccess 'remoteadmin'
```

Then from Mac, mount with `smb://<PC_HOSTNAME>/models` etc. No junctions visible inside, so listing works cleanly.

To list or remove existing shares:

```powershell
Get-SmbShare
Remove-SmbShare -Name 'models' -Force
```

---

## Step 6 — Mount from Finder and File Explorer

### Mac → PC

Finder → **⌘K** → enter:

```
smb://<PC_HOSTNAME>/G$
smb://<PC_HOSTNAME>/models
```

Check **"Remember in Keychain"** so you only type the password once.

Drag the mounted volumes to your Finder sidebar Favorites for one-click reconnect.

### PC → Mac

File Explorer address bar:

```
\\<MAC_HOSTNAME>\<YOUR_MAC_USERNAME>
```

Check "Remember my credentials" in the auth dialog.

### iOS

iPhone/iPad with Tailscale app running:

1. **Files** app → **⋯** (top-right) → **Connect to Server**
2. Enter `smb://<PC_HOSTNAME>/<share>`
3. Auth with `remoteadmin` and password

Works on cellular with no Wi-Fi.

---

## Quick file drops: Taildrop

For one-off transfers without mounting anything:

```bash
# Mac → PC
tailscale file cp ./photo.png <PC_HOSTNAME>:

# Receive on the other side (or via the menu bar / tray app)
tailscale file get .
```

Windows tray icon also has a "Send file to device" entry.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Input/output error` mounting `C$` | LocalAccountTokenFilterPolicy not set | Step 4 above |
| `fts_read: Invalid argument` listing a folder | Folder contains NTFS junctions/reparse points | Use a named share rooted past the junction layer (Step 5) |
| "There was a problem connecting" in Finder | Stale credentials in Keychain, or auth failing | Keychain Access → search server name → delete entries; reconnect |
| Authentication fails despite correct password | Using PIN instead of MSA password | Use the MSA web password (login.live.com), or switch to a dedicated local admin (Step 3) |
| `smbutil` connects but mount fails | Network category set to Public on Windows | `Set-NetConnectionProfile -InterfaceAlias Tailscale -NetworkCategory Private` |
| smbd not running on Mac after reboot | `kickstart -k` is one-shot | `enable` (Step 2) makes it persistent across reboots |

---

## What you do not need

- Port forwarding on your router
- Dynamic DNS
- A "real" VPN (OpenVPN/WireGuard config files)
- Exposing SMB to the public internet
- Static IPs

Tailscale handles all of it. The same `smb://<hostname>` URL works on every network you'll ever sit on.
