const CACHE = "meghdrishti-v3";
const ASSETS = [
    "/",
    "/disaster-alerts",
    "/warnings",
    "/offline",
    "/static/css/style.css",
    "/static/js/dashboard.js",
    "/static/manifest.json",
    "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
];

self.addEventListener("install", e => 
    e.waitUntil(
        caches.open(CACHE)
            .then(c => c.addAll(ASSETS))
            .then(() => self.skipWaiting())
    )
);

self.addEventListener("activate", e => 
    e.waitUntil(self.clients.claim())
);

self.addEventListener("fetch", e => {
    if (e.request.method !== "GET") return;
    e.respondWith(
        fetch(e.request)
            .then(r => {
                if (r.ok) {
                    const copy = r.clone();
                    caches.open(CACHE).then(c => c.put(e.request, copy));
                }
                return r;
            })
            .catch(() => caches.match(e.request).then(r => {
                if (r) return r;
                if (e.request.mode === "navigate") return caches.match("/offline");
                return caches.match("/");
            }))
    );
});

self.addEventListener("push", e => {
    let d = {
        title: "MeghDrishti disaster alert",
        body: "A new early-warning alert is available.",
        url: "/disaster-alerts",
        tag: "meghdrishti-alert",
        requireInteraction: true
    };
    try {
        if (e.data) d = { ...d, ...e.data.json() };
    } catch (_) {}
    
    e.waitUntil(
        self.registration.showNotification(d.title, {
            body: d.body,
            tag: d.tag,
            requireInteraction: d.requireInteraction,
            data: { url: d.url }
        })
    );
});

self.addEventListener("notificationclick", e => {
    e.notification.close();
    e.waitUntil(
        clients.matchAll({ type: "window", includeUncontrolled: true }).then(cs => {
            for (const c of cs) {
                if ("focus" in c) {
                    c.navigate(e.notification.data?.url || "/disaster-alerts");
                    return c.focus();
                }
            }
            return clients.openWindow(e.notification.data?.url || "/disaster-alerts");
        })
    );
});
