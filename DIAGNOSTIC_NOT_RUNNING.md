# Diagnostics Not Executing - Root Cause

## Problem

The diagnostic console.log statements added to `client/src/hooks/index.js` are not appearing in the browser console.

## Root Cause

**The Docker container is serving OLD CODE from 2 days ago.**

```
CONTAINER ID   IMAGE             CREATED      STATUS
7e904fd0a110   geosense-client   2 days ago   Up 2 days
```

The container was built 2 days ago and is serving the code that was present at that time. The diagnostic changes made today are only in the source files on your host machine, but the running container doesn't have them.

## Why Hot-Reload Isn't Working

While Vite dev server normally supports hot-reload, Docker volume mounting may not be configured correctly, or the container isn't watching the host filesystem for changes.

## Solution

You must rebuild and restart the client container to load the new code:

```bash
# Stop the old container
docker compose stop client

# Rebuild with new code
docker compose build client

# Start the new container
docker compose up -d client

# Or do all at once:
docker compose up -d --build client
```

## After Rebuild, You Should See

When you refresh the browser at http://localhost:3000, the console should immediately show:

```
════════════════════════════════════════════════════════════════════════════════
[GEOSENSE DIAGNOSTICS ACTIVE] - hooks/index.js loaded
Timestamp: 2026-09-13T...
MAPBOX_TOKEN available: true
════════════════════════════════════════════════════════════════════════════════

[GEOSENSE DIAGNOSTICS] useMapbox hook called
  activeCity: null
  activeLayers: {...}
  aqiSurface: false
  ndviSurface: false

[GEOSENSE DIAGNOSTICS] Map initialization useEffect triggered
  containerRef.current exists: true
  mapRef.current exists: false

🗺️ MAPBOX CONFIGURATION
  Token exists: true
  Token starts with 'pk.': true
  Token length: 150
  Token first 20 chars: pk.eyJ1IjoiZHJhc2hp...
  Map style: mapbox://styles/mapbox/dark-v11
```

Then when you select Mumbai and click NDVI, you should see:

```
🌿 NDVI SURFACE DATA RECEIVED
  4. ndviSurface data: {...}
  9. Exact NDVI image URL: http://localhost:8000/...

🔍 NDVI RUNTIME DIAGNOSTIC
  1. activeLayers: {...}
  2. getPrimaryLayerId(activeLayers): "ndvi"
  ...
```

And any Mapbox errors:

```
❌ Mapbox Error #1
  11. Mapbox error event: {...}
  ...
```

## Diagnostics Added

To verify the code is running, I added three unmistakable startup logs:

1. **Module-level log** (runs immediately when hooks/index.js loads)
2. **useMapbox hook call log** (runs every time the hook is called)
3. **Map initialization useEffect log** (runs when map is created)

These will definitively show whether the new code is loaded.

## Current Container Commands to Run

```bash
# From the GeoSense directory:
cd "C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense"

# Rebuild and restart client:
docker compose up -d --build client

# Verify container was just rebuilt:
docker ps --filter "name=client"
# Should show CREATED as "X seconds ago" not "2 days ago"

# Watch container logs:
docker compose logs -f client
```

## Verification Steps

1. Run the rebuild command above
2. Verify container shows "CREATED" recently (seconds/minutes ago, not days)
3. Open http://localhost:3000
4. Open browser DevTools Console (F12)
5. Look for the `[GEOSENSE DIAGNOSTICS ACTIVE]` message
6. If you see it: diagnostics are working, proceed with testing
7. If you don't see it: the container still has old code, try force rebuild:
   ```bash
   docker compose down
   docker compose build --no-cache client
   docker compose up -d
   ```
