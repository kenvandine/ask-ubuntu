* **name**: ask-ubuntu
* **description**: AI-powered Ubuntu assistant with deep system awareness
* **snapcraft**: https://github.com/kenvandine/ask-ubuntu
* **upstream**: https://github.com/kenvandine/ask-ubuntu
* **upstream-relation**: maintainer
* **interfaces**:
  * **hardware-observe**:
    * **request-type**: auto-connection
    * **reasoning**: Ask Ubuntu reads hardware facts (CPU/GPU model, thermal and power context, device info) to give accurate diagnostics and guidance for the current machine.
  * **system-observe**:
    * **request-type**: auto-connection
    * **reasoning**: Ask Ubuntu inspects runtime system state (process/service presence, memory/pressure, uptime, and related telemetry) so troubleshooting answers are grounded in live system facts.
  * **desktop-launch**:
    * **request-type**: auto-connection
    * **reasoning**: Ask Ubuntu uses the limited snapd socket exposed by this interface (`/run/snapd-snap.socket`) to read installed snap metadata (`/v2/snaps`, `/v2/snaps/{name}`), including tracking-channel/version context, so package guidance reflects what is actually installed.
  * **system-files**:
    * **request-type**: auto-connection
    * **reasoning**: All `system-files` plugs below are strictly read-only. Ask Ubuntu does not modify host files and only reads package metadata needed to answer package-management questions accurately.
    * **read-only-plugs**:
      * **var-lib-dpkg**: read-only access to `/var/lib/snapd/hostfs/var/lib/dpkg` so the app can parse dpkg status and determine installed deb packages.
      * **var-lib-apt-lists**: read-only access to `/var/lib/snapd/hostfs/var/lib/apt/lists` so the app can determine apt package availability from local apt index files.
      * **usr-share-man**: read-only access to `/var/lib/snapd/hostfs/usr/share/man` so the app can index local man pages via `system-files`. This may be replaced with `system-packages-doc` eventually if my snapd PR lands https://github.com/canonical/snapd/pull/16681
      * **usr-share-help**: read-only access to `/var/lib/snapd/hostfs/usr/share/help` so the app can index local Ubuntu help files via `system-files`. This may be replaced with `system-packages-doc` eventually if my snapd PR lands https://github.com/canonical/snapd/pull/16681
