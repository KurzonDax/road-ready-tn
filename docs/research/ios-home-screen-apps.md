# How iPhone Home Screen web apps treat storage, cookies and sign-in

Research for [#3](https://github.com/KurzonDax/road-ready-tn/issues/3), part of the self-hosted Instance map ([#2](https://github.com/KurzonDax/road-ready-tn/issues/2)).

All sources were read on **2026-10-15**. Where a fact comes from WebKit source code, it is from the `main` branch at commit [`c526785`](https://github.com/WebKit/WebKit/commit/c526785513ba334a7a24e5cc649c99f11336038a) (the latest commit to touch `ResourceLoadStatisticsStore.cpp` as of that date). Open-source WebKit `main` is what Safari is built from, but a shipping iOS release can lag or differ. Treat source-code findings as strong evidence, not a guarantee for a given iOS version.

Labels used below:

- **Confirmed**: stated by a primary source (WebKit blog, Apple developer docs or WWDC session, WebKit source or bug tracker, a W3C spec, or MDN's browser-compat-data).
- **Inferred**: follows from confirmed facts, but no source says it directly.
- **Not confirmed**: no primary source found. Needs a test on a real iPhone.

## Short answers

1. **The 7-day storage cap does not apply to Home Screen web apps.** In Safari, script-writable storage (localStorage, IndexedDB, service worker registrations and caches, sessionStorage) is deleted after 7 days of Safari use without user interaction on the site. Cookies are not part of that rule. Home Screen web apps keep their own count of days of use, and current WebKit source exempts the Home Screen web app's domain from this deletion entirely.
2. **Storage is separate.** A Home Screen web app has its own cookies and storage, apart from Safari. Since iOS 17.2, adding the app copies Safari's cookies (including a cookie sign-in) into it once, at the moment it is added. Nothing else is copied, and nothing is shared after that, in either direction.
3. **A server-set `HttpOnly`, `Secure` session cookie is not capped at 7 days** in Safari or in a Home Screen app, as long as the page's own server sets it. The 7-day caps hit cookies written by script (`document.cookie`) and cookies set by a third-party server dressed up as first party (CNAME or IP-address cloaking). An overall upper limit (400 days in the cookie spec draft) is not confirmed for Safari.
4. **Sign-in methods:**
   - Username and password with a same-origin cookie session works and is Apple's recommended pattern.
   - Passkeys are recommended by Apple for web apps and need HTTPS on a real domain name. Some reports of flaky prompts in Home Screen apps exist.
   - HTTP Basic auth prompts in standalone mode are not confirmed either way.
   - A tapped one-time sign-in link opens in the browser, not in the installed app, so it signs in Safari and not the app.
   - Redirects out of scope open in an in-app Safari View Controller sheet on iOS.
5. **Storage persistence, service workers, manifest:**
   - `navigator.storage.persist()` exists since Safari 15.2 (full Storage API since iOS 17). WebKit grants it by heuristics, including "opened as a Home Screen web app".
   - Service workers and Cache Storage have worked since iOS 11.3. Background Sync is not supported.
   - Manifest `start_url`, `scope` and `display: standalone` work since iOS 11.3, and `id` since 16.4. Links outside `scope` open in Safari View Controller.
   - Since iOS 26, every site added to the Home Screen opens as a web app by default, manifest or not.

## 1. The 7-day cap on script-writable storage

**The rule in Safari (confirmed).** In March 2020 ITP started deleting all of a website's script-writable storage "after seven days of Safari use without user interaction on the site". The storage types covered are IndexedDB, LocalStorage, Media keys, SessionStorage, and Service Worker registrations and cache. Days are counted as days Safari is used, not calendar days.
Source: WebKit blog, "Full Third-Party Cookie Blocking and More", 2020-03-24, https://webkit.org/blog/10218/full-third-party-cookie-blocking-and-more/

**Home Screen web apps (confirmed, 2020 statement).** The same post says:

> "Web applications added to the home screen are not part of Safari and thus have their own counter of days of use. Their days of use will match actual use of the web application which resets the timer. We do not expect the first-party in such a web application to have its website data deleted. If your web application does experience website data deletion, please let us know since we would consider it a serious bug."

**The current rule in WebKit source (confirmed in source).** ITP's data-removal pass skips any domain in `domainsExemptFromWebsiteDataDeletion()`. That set includes the standalone application's domain, app-bound domains, managed domains, and domains the host app marks as "persisted". The comment at the call site reads: "Domains permanently configured to be exempt. This can be home screen web applications, app-bound domains, or similar."
Sources:
- `domainsExemptFromWebsiteDataDeletion()`: https://github.com/WebKit/WebKit/blob/c526785513ba334a7a24e5cc649c99f11336038a/Source/WebKit/NetworkProcess/Classifier/ResourceLoadStatisticsStore.cpp#L809-L818
- The skip in `registrableDomainsToDeleteOrRestrictWebsiteDataFor()`: https://github.com/WebKit/WebKit/blob/c526785513ba334a7a24e5cc649c99f11336038a/Source/WebKit/NetworkProcess/Classifier/ResourceLoadStatisticsStore.cpp#L2917-L2919
- Where the standalone domain comes from (the data store's `standaloneApplicationURL`): https://github.com/WebKit/WebKit/blob/c526785513ba334a7a24e5cc649c99f11336038a/Source/WebKit/UIProcess/WebsiteData/Cocoa/WebsiteDataStoreCocoa.mm#L234

The same pass also skips domains the user has recently interacted with through Web Push (line 2921).

**The 7-day removal keeps cookies (confirmed in source).** For an ordinary first-party site, the short-window rule is `shouldRemoveAllButCookiesFor`: it deletes script-written storage and leaves cookies alone. Cookies are deleted only for domains ITP has classified as prevalent (tracker) resources with no user interaction in the 30-day window (`shouldRemoveAllWebsiteDataFor`).
Source: https://github.com/WebKit/WebKit/blob/c526785513ba334a7a24e5cc649c99f11336038a/Source/WebKit/NetworkProcess/Classifier/ResourceLoadStatisticsStore.cpp#L2849-L2873 and the loop at L2928-L2936

**What this means here (inferred).** The app currently keeps progress in `localStorage`. In a Safari tab that is at risk after 7 days of Safari use without visiting. In a Home Screen app it is not at risk from ITP. Progress kept on the server, plus a sign-in held in a server-set cookie, is safe in both places. Even in Safari, the 7-day rule does not delete the cookie.

**Persistent storage mode and the 7-day rule (partly confirmed).** The 2023 storage-policy post says an origin is excluded from quota/LRU eviction "if ... its storage is in persistent mode", and lists ITP inactivity as one cause of eviction. WebKit source exempts "persisted" domains from ITP deletion. However, those domains are set by the embedding app through `WebsiteDataStore::setPersistedSiteURLs` ([source](https://github.com/WebKit/WebKit/blob/c526785513ba334a7a24e5cc649c99f11336038a/Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp#L2086-L2096)). I could **not confirm** that a page calling `navigator.storage.persist()` in Safari puts its domain in that set. Do not rely on `persist()` to beat the 7-day rule in a Safari tab.

**Changes over time.**
- 2019 (ITP 2.1, announced 2019-02-21; the post does not name the iOS version): script-set cookies capped to 7 days.
- 2020 (iOS 13.4): the cap extended to all script-writable storage. Home Screen apps have their own day counter.
- iOS 17.4 beta (early 2024), EU only: Home Screen web apps briefly opened in Safari as plain bookmarks. That would have put them under Safari's rules. The final iOS 17.4 release restored standalone web apps. Sources: WebKit bug 268643, https://bugs.webkit.org/show_bug.cgi?id=268643 (comments dated 2024-03-01 and 2024-03-11). Apple's own announcement of the reversal is no longer on its developer DMA page, so this rests on the bug thread. Not relevant to a US user, but noted.

## 2. Is Home Screen app storage separate from Safari's?

**Yes, separate (confirmed).**
- WWDC23, "What's new in web apps": "Home Screen web apps have a standalone, app-like experience on iOS, with separate cookies and storage from the browser." https://developer.apple.com/videos/play/wwdc2023/10120/
- WebKit bug 181849, "Add to homescreen apps don't share storage with Safari". A WebKit engineer commented on 2022-02-01: "The current behavior (on Apple platforms) is by design. ... Home Screen apps are created as isolated entities without shared state with the browser." https://bugs.webkit.org/show_bug.cgi?id=181849

This covers cookies, localStorage, IndexedDB, service worker registrations and Cache Storage. The WWDC wording is "cookies and storage", and the WebKit wording is "without shared state".

**Sign-in carries over once, at install, cookies only (confirmed; changed in iOS 17.2).**
WebKit blog, "WebKit Features in Safari 17.2", 2023-12-11, under "Login cookies": in iOS 17.2 and iPadOS 17.2, when the user taps "Add to Home Screen" from Safari, Safari View Controller or another browser, "the cookies are copied over, including the information about login state. This will only work if the authentication state is stored within cookies. No other kind of local storage is copied over. After a user adds a web app to the Home Screen, no other website data is shared." https://webkit.org/blog/14787/webkit-features-in-safari-17-2/

Before iOS 17.2 nothing was copied, so a user who signed in in Safari had to sign in again in the installed app. A Mac Dock web app got the same copy-once behavior in Safari 17.0 (https://webkit.org/blog/14445/webkit-features-in-safari-17-0/).

**The reverse direction (confirmed for Mac, inferred for iOS).** WWDC23, about Mac web apps: "If the user logs into your web page in their default browser, they will not be logged into the web app that has already been added to the Dock, since cookies and storage are separate after the web app is added." Given the iOS separation statements above, the same holds on iPhone. A sign-in done inside the installed app never appears in Safari, and a sign-in done in Safari after install never reaches the app.

**What this means here (inferred).** If the Learner signs in in Safari first and then adds the app to the Home Screen, they arrive signed in, provided the session lives only in a cookie. Any progress in Safari's `localStorage` (`tn-permit-daily-v1`) does not come along. A one-time import of browser progress has to happen in the same context that holds it.

## 3. How long does a server-set `HttpOnly`, `Secure` session cookie last?

**Script-set cookies are capped at 7 days; server-set ones are not (confirmed).** ITP 2.1: "persistent cookies created through document.cookie, are capped to a seven day expiry", and "Cookies created through document.cookie cannot be HttpOnly". The advice is to "set your authentication cookies in an HTTP response and mark them Secure and HttpOnly".
Source: WebKit blog, "Intelligent Tracking Prevention 2.1", 2019-02-21, https://webkit.org/blog/8613/intelligent-tracking-prevention-2-1/

**Server-set cookies from "cloaked" third parties are capped at 7 days (confirmed). This does not affect a single-server app.**
- Since iOS 14 / Safari 14, cookies set in HTTP responses to third-party CNAME-cloaked requests are capped to 7 days. https://webkit.org/blog/11338/cname-cloaking-and-bounce-tracking-defense/ (2020-11-12)
- Since Safari 16.4 / iOS 16.4 (WebKit commit landed 2022-10-21), the same cap applies when there is no CNAME but the responding server's IP address shares less than half its prefix (16 bits IPv4, 64 bits IPv6) with the main page's server IP. Commit message: https://github.com/WebKit/WebKit/commit/b0305b173106ba984cbc0475b3681daea137390c ; bug: https://bugs.webkit.org/show_bug.cgi?id=246477 . This change was not in Apple's Safari 16.4 release notes.

An Instance where the page and the sign-in endpoint come from the same host is unaffected by either rule (inferred). If sign-in were ever split onto a separate host at a very different IP address, its cookies would be capped at 7 days.

**ITP's 7-day storage deletion does not remove first-party cookies (confirmed in source).** See section 1: the short-window rule removes "all but cookies".

**General upper limit (not confirmed).** The cookie spec draft (RFC 6265bis) caps `Expires`/`Max-Age` at 400 days, and Chrome enforces this. A 2022 webkit-dev thread discussed WebKit's position, but the archive (https://lists.webkit.org/pipermail/webkit-dev/2022-January/032089.html) returned 403 when fetched, so I could not confirm what Safari ships. Any sensible session lifetime (days to a few months) is far below this.

**Session cookies with no `Expires` in a Home Screen app (not confirmed).** No primary source says when a Home Screen app's "browser session" ends, for example when the app is swiped away or when iOS stops it in the background. A cookie with no expiry may vanish more often than expected. Inferred recommendation: give the session cookie an explicit `Max-Age`.

## 4. Which sign-in methods work in a standalone Home Screen app?

**Username and password form with a cookie session: works (confirmed as the recommended pattern).** Apple's guidance in WWDC23 and the Safari 17.0 and 17.2 posts is to keep authentication state in cookies. That is also what lets the sign-in survive the install-time copy (section 2). WWDC23 (Mac section) says web apps "work with AutoFill credentials from iCloud Keychain and from third-party apps that have adopted the Credential Provider Extension API". No iOS-specific statement on AutoFill in Home Screen apps was found (not confirmed for iOS).

**HTTP Basic auth prompts: not confirmed.** No WebKit or Apple source says whether a standalone Home Screen app shows the browser's Basic-auth dialog. The closest report is for a different WebKit browser (Orion), where an installed web app opened blank with no prompt. Basic auth credentials also cannot be signed out of cleanly and cannot serve two account types. Avoid them for this app. If an Instance owner puts Basic auth in front as an extra gate, test it on an iPhone first.

**Passkeys (WebAuthn): supported API, recommended by Apple, with caveats.**
- WebAuthn `PublicKeyCredential` is in Safari since 13. Conditional mediation (passkey autofill) since 16, and the JSON helpers since 18.4. Source: MDN browser-compat-data, `api/PublicKeyCredential.json`, https://github.com/mdn/browser-compat-data/blob/main/api/PublicKeyCredential.json (`safari_ios` mirrors `safari`).
- WWDC23, in the web apps session: "consider adopting passkeys for authentication on your site" (confirmed as recommended, not as a per-platform guarantee).
- Requirements from the spec: `PublicKeyCredential` is `[SecureContext]` (HTTPS only), and creating a credential throws `SecurityError` if the origin's effective domain "is not a valid domain". The RP ID "is based on a host's domain name". So passkeys need HTTPS on a real domain name, not a bare IP address. https://www.w3.org/TR/webauthn-3/
- Caveat (not a primary source): an Apple Developer Forums thread from February 2026 (iOS 18.6.2, no Apple reply) reports duplicate or stuck passkey prompts that are more frequent when the login page runs from the Home Screen. https://developer.apple.com/forums/thread/815784 . Passkeys need a fallback, and setup needs a step the Helper can do.

**One-time sign-in links: open in the browser, not the app (confirmed for Mac, inferred for iOS).**
- WWDC23: "Since links from email will open in the default browser, this will not automatically sign users in to the web app that they already have. You may want to provide an alternative one-time code in the email."
- Nothing gives a Home Screen web app a way to claim links. MDN browser-compat-data lists the manifest's `protocol_handlers` and `launch_handler` as not supported in Safari (https://github.com/mdn/browser-compat-data/tree/main/manifests/webapp, `protocol_handlers.json`, `launch_handler.json`).
- So on iPhone, a tapped link from Messages or Mail opens in Safari (or the default browser). Because storage is separate (section 2), it signs in that browser and not the installed app. A short code typed into the app works; a link does not.

**Redirects to another origin (confirmed).**
- WWDC23: "In Home Screen web apps on iOS, links outside the scope will open in Safari View Controller."
- For OAuth: "Authentication through OAuth on a third-party domain will still open in your web app. This is done through heuristics ... Links loaded through window.open will always open in the web app regardless of scope."
- Not confirmed: whether cookies set inside that Safari View Controller sheet land in the web app's cookie store.

Inferred conclusion: keep every step of sign-in on the Instance's own origin and within the manifest `scope`.

## 5. `navigator.storage.persist()`, service workers, offline, `start_url` and `scope`

**Storage API (confirmed).**
- `navigator.storage.persist()` and `persisted()` are in Safari since 15.2, and `estimate()` since 17 (MDN browser-compat-data, `api/StorageManager.json`).
- Full Storage API support came in Safari 17.0 / iOS 17 (https://webkit.org/blog/14445/webkit-features-in-safari-17-0/).
- WebKit "Updates to Storage Policy" (2023-08-10), https://webkit.org/blog/14403/updates-to-storage-policy/ :
  - "WebKit currently grants a request based on heuristics like whether the website is opened as a Home Screen Web App."
  - Persistent mode excludes the origin from eviction.
  - Default is best-effort.
- Quotas from iOS 17 (same post):
  - A browser app gets up to 60% of disk per origin and 80% overall.
  - Other apps get 15% and 20%.
  - A standalone Home Screen web app "has the same origin quota and overall quota as when it is opened in a browser app".
  - Quotas "might change based on factors like existing usage and site visit frequency", so `QuotaExceededError` still has to be handled.

**Service workers and offline caching (confirmed).**
- `ServiceWorker` and `CacheStorage` are in Safari since 11.1. iOS 11.3 is the first iOS with service workers (MDN browser-compat-data, `api/ServiceWorker.json`, `api/CacheStorage.json`).
- Background Sync (`SyncManager`) is not supported (`version_added: false`, tracking bug https://webkit.org/b/182565).
- In Safari (not Home Screen apps), service worker registrations and caches are part of the 7-day deletion (section 1).
- Lockdown Mode (iOS 16.4+) disables service workers and the Cache API (https://webkit.org/blog/13966/webkit-features-in-safari-16-4/).
- Web Push to Home Screen apps works since iOS 16.4 (https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/). Out of scope here.

**Manifest `start_url`, `scope`, `display`, `id` (confirmed).**
- MDN browser-compat-data (`manifests/webapp/*.json`):
  - `start_url`, `scope` and `display: standalone` are supported since iOS 11.3.
  - `id` is supported since iOS 16.4.
  - `display: fullscreen` and `minimal-ui` are not supported.
- WWDC23 on these members:
  - "All web apps have an associated scope. Links within the scope open within the web app. The default scope is the host of the webpage used to create the web app."
  - "The start_url is the URL that is loaded when the web app is first opened."
  - "Any links within the scope will stay within the web app and any links outside the scope will open in the default browser."
  - On iOS, out-of-scope links open in Safari View Controller.
  - If no `id` is given, it falls back to `start_url`.
- Multiple installs of the same site are allowed. Each install is identified by its name plus manifest `id` (WebKit Web Push post, 2023-02-16).

**Changed in iOS 26 (confirmed).** "By default, every website added to the Home Screen opens as a web app" on iOS and iPadOS 26, even without a manifest. The user can turn off "Open as Web App" when adding it, and then it is a bookmark that opens in the default browser. Before iOS 26, a site needed `display: standalone`/`fullscreen` in its manifest, or the `apple-mobile-web-app-capable` meta tag, to open as a web app.
Source: WebKit blog, "News from WWDC25: WebKit in Safari 26 beta", 2025-06-09, https://webkit.org/blog/16993/news-from-wwdc25-web-technology-coming-this-fall-in-safari-26-beta/

## Not confirmed: test on a real iPhone

- Whether `navigator.storage.persist()` in a Safari tab exempts the site from the 7-day script-storage deletion.
- When a cookie without `Expires`/`Max-Age` is dropped in a Home Screen app.
- Whether an HTTP Basic auth prompt appears in a standalone Home Screen app.
- Whether cookies set in the Safari View Controller sheet (out-of-scope navigation) reach the Home Screen app's cookie store.
- Whether removing the Home Screen icon deletes that app's cookies and storage.
- Safari's maximum cookie lifetime (400-day cap or none).
- How reliable passkey prompts are in a Home Screen app on current iOS.
