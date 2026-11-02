# NDVI Lifecycle Fix Summary

## Changes Made

**File:** `client/src/hooks/index.js`  
**Function:** NDVI useEffect (dependency: `[ndviSurface]`)  
**Lines Modified:** ~212-365

---

## OLD Control Flow (BROKEN)

```javascript
useEffect(() => {
  ndviSurfaceRef.current = ndviSurface;
  const map = mapRef.current;
  
  // ❌ PROBLEM: Early return if style not loaded
  if (!map || !map.isStyleLoaded() || !ndviSurface) return;
  
  const sync = () => {
    // Create source/layer
    map.addSource(NDVI_SURFACE_SOURCE, {...});
    map.addLayer(NDVI_SURFACE_LAYER, {...});
  };
  
  if (map.isStyleLoaded()) sync();
  else map.once("idle", sync);  // ← Never reached if early return above
  
}, [ndviSurface]);
```

**Problem:**
- When `ndviSurface` data arrived, `map.isStyleLoaded()` returned `false`
- Effect executed early return BEFORE registering the 'idle' listener
- sync() never executed → source/layer never created

---

## NEW Control Flow (FIXED)

```javascript
useEffect(() => {
  ndviSurfaceRef.current = ndviSurface;
  const map = mapRef.current;
  
  // ✅ FIXED: Early return ONLY if map or data unavailable
  if (!map || !ndviSurface) return;
  
  const sync = () => {
    // Defensive check inside sync()
    if (!map.isStyleLoaded()) {
      console.warn("Style not loaded - aborting");
      return;
    }
    
    // Create source/layer (only if style is ready)
    map.addSource(NDVI_SURFACE_SOURCE, {...});
    map.addLayer(NDVI_SURFACE_LAYER, {...});
  };
  
  if (map.isStyleLoaded()) {
    // Style ready NOW → execute immediately
    sync();
  } else {
    // Style NOT ready → wait for style.load event
    const styleLoadCallback = () => sync();
    map.once("style.load", styleLoadCallback);
    
    // Cleanup: remove listener if effect re-runs
    return () => {
      map.off("style.load", styleLoadCallback);
    };
  }
  
}, [ndviSurface]);
```

---

## Specific Code Changes

### Change 1: Removed `map.isStyleLoaded()` from early return condition

**Line ~212:**

**OLD:**
```javascript
const willEarlyReturn = !map || !map.isStyleLoaded() || !ndviSurface;
```

**NEW:**
```javascript
const willEarlyReturn = !map || !ndviSurface;
```

**Why:** Allows effect to proceed to sync decision logic even if style not yet loaded.

---

### Change 2: Removed style loading from early return messages

**Lines ~215-227:**

**OLD:**
```javascript
if (willEarlyReturn) {
  if (!map) {
    console.warn("❌ Early return: map does not exist");
  } else if (!map.isStyleLoaded()) {
    console.warn("❌ Early return: map.isStyleLoaded() === false");
    console.warn("Map will wait for 'idle' event");
  } else if (!ndviSurface) {
    console.warn("❌ Early return: ndviSurface is null/undefined");
  }
  console.groupEnd();
  return;
}
```

**NEW:**
```javascript
if (willEarlyReturn) {
  if (!map) {
    console.warn("❌ Early return: map does not exist");
  } else if (!ndviSurface) {
    console.warn("❌ Early return: ndviSurface is null/undefined");
  }
  console.groupEnd();
  return;
}
```

---

### Change 3: Added defensive check inside sync()

**Lines ~238-244:**

**NEW:**
```javascript
const sync = () => {
  console.group("🟢 [NDVI SYNC] sync() function starting");
  console.log("  6. map.isStyleLoaded() inside sync:", map.isStyleLoaded());
  
  // Defensive check: verify style is loaded before proceeding
  if (!map.isStyleLoaded()) {
    console.warn("  ⚠️ Style not loaded inside sync() - aborting");
    console.groupEnd();
    return;
  }
  
  const existingSource = map.getSource(NDVI_SURFACE_SOURCE);
  // ... rest of sync logic
};
```

**Why:** Even if `map.isStyleLoaded()` was true at decision point, it could become false by the time sync() executes (rare but possible). This ensures sync() never attempts addSource/addLayer when style isn't ready.

---

### Change 4: Changed from 'idle' to 'style.load' event

**Lines ~345-369:**

**OLD:**
```javascript
} else {
  console.warn("Style NOT loaded - registering 'idle' event listener");
  
  const idleCallback = () => {
    console.group("🟡 [NDVI IDLE] 'idle' event fired");
    sync();
  };
  
  map.once("idle", idleCallback);
}
```

**NEW:**
```javascript
} else {
  console.warn("Style NOT loaded - registering 'style.load' event listener");
  
  const styleLoadCallback = () => {
    console.group("🟢 [NDVI STYLE LOAD] 'style.load' event fired");
    console.log("  13. map.isStyleLoaded() when style.load fires:", map.isStyleLoaded());
    console.log("  ✅ Now executing sync() in response to style.load event");
    sync();
  };
  
  map.once("style.load", styleLoadCallback);
  
  // Return cleanup function
  return () => {
    console.log("🧹 [NDVI EFFECT CLEANUP] Removing style.load listener");
    map.off("style.load", styleLoadCallback);
  };
}
```

**Why `style.load` instead of `idle`:**
- `'style.load'` fires specifically when the Mapbox style finishes loading
- `'idle'` fires when map becomes idle (no tiles loading, no camera movement)
- In the presence of continuous tile loading errors, `idle` may never fire
- `style.load` is the correct lifecycle event for "style is now ready for layer/source operations"

---

### Change 5: Added cleanup function

**Lines ~366-369:**

**NEW:**
```javascript
return () => {
  console.log("🧹 [NDVI EFFECT CLEANUP] Removing style.load listener");
  map.off("style.load", styleLoadCallback);
};
```

**Why:** If the effect re-runs before style.load fires (e.g., user leaves Mumbai and returns), the old listener must be removed to prevent:
- Multiple listeners firing
- Memory leaks
- sync() executing with stale closure values

---

## Execution Flow Comparison

### OLD (Broken):
```
ndviSurface arrives
  ↓
useEffect fires
  ↓
map.isStyleLoaded() === false
  ↓
❌ Early return
  ↓
(no listener registered)
  ↓
(style loads later)
  ↓
❌ Nothing happens - source/layer never created
```

### NEW (Fixed):
```
ndviSurface arrives
  ↓
useEffect fires
  ↓
map exists? YES, ndviSurface exists? YES
  ↓
✅ Proceed to sync decision
  ↓
map.isStyleLoaded()?
  ├─ YES → sync() immediately
  │   ↓
  │   style loaded check passes
  │   ↓
  │   ✅ source/layer created
  │
  └─ NO → register 'style.load' listener
      ↓
      (style loads)
      ↓
      style.load fires
      ↓
      sync() executes
      ↓
      style loaded check passes
      ↓
      ✅ source/layer created
```

---

## Why `style.load` Instead of `idle`

### Problem with `idle`:
- `idle` event fires when the map is not actively loading tiles or animating
- In the user's case: continuous Mapbox tile errors prevent `idle` from ever firing
- The map keeps retrying failed tiles → never becomes truly idle
- Even if tiles eventually succeed, `idle` is semantically wrong for "style is ready"

### Why `style.load` is correct:
- `style.load` fires once when the style's layers/sources structure is loaded
- It fires BEFORE tiles are loaded (tiles are async content, not structure)
- This is the correct Mapbox lifecycle event for "you can now add sources/layers"
- Tile loading errors don't prevent `style.load` from firing
- Matches Mapbox documentation: "Fired after the last batch of gl-style definitions are applied"

### Mapbox Event Lifecycle:
```
map created
  ↓
style requested
  ↓
style JSON downloaded
  ↓
🔔 'style.load' fires  ← Safe to addSource/addLayer
  ↓
tiles requested (async, can fail)
  ↓
tiles loaded (or retry if fail)
  ↓
🔔 'idle' fires  ← Map has no pending operations
```

---

## What Changed (Summary)

| Aspect | OLD | NEW |
|--------|-----|-----|
| **Early return condition** | `!map \|\| !style.isLoaded() \|\| !ndviSurface` | `!map \|\| !ndviSurface` |
| **Effect proceeds when** | Map exists AND style loaded AND data exists | Map exists AND data exists |
| **Style check location** | Before sync decision | Inside sync() function |
| **Fallback event** | `'idle'` | `'style.load'` |
| **Cleanup** | None | Removes style.load listener |
| **Blocks source creation** | YES (early return) | NO (registers listener) |

---

## Testing Verification

After this fix, the expected behavior:

### Scenario 1: Style loads before data
```
1. User selects Mumbai
2. Map created, style starts loading
3. style.load fires → setupLayers() runs
4. ndviSurfaceRef.current === null → source not created in setupLayers
5. NDVI data fetch completes → setNdviSurface(data)
6. NDVI useEffect fires
7. map.isStyleLoaded() === true
8. ✅ sync() called immediately
9. ✅ Source/layer created
```

### Scenario 2: Data arrives before style loads (user's case)
```
1. User selects Mumbai
2. Map created, style starts loading (slow/errors)
3. NDVI data fetch completes quickly → setNdviSurface(data)
4. NDVI useEffect fires
5. map.isStyleLoaded() === false
6. ✅ Registers style.load listener (does NOT early return)
7. (style finishes loading)
8. style.load event fires
9. ✅ sync() called
10. ✅ Source/layer created
```

---

## Files Modified

- `client/src/hooks/index.js` - NDVI useEffect section

## Files NOT Modified

- ✅ Backend unchanged
- ✅ API unchanged
- ✅ NDVI PNG generation unchanged
- ✅ Database unchanged
- ✅ Layer ordering unchanged
- ✅ React state management unchanged
- ✅ setupLayers() unchanged
- ✅ Other useEffects unchanged

---

## Next Steps

1. Rebuild client container: `docker compose up -d --build client`
2. Hard refresh browser: `Ctrl + Shift + R`
3. Select Mumbai
4. Click NDVI layer
5. Verify NDVI raster appears on map

Expected console logs:
```
🔵 [NDVI EFFECT] useEffect fired
  2. map exists: true
  3. ndviSurface exists: true
  4. map.isStyleLoaded(): false  ← Style not ready yet
  ✅ Map and ndviSurface available - proceeding to sync logic

🔵 [NDVI EFFECT] Deciding sync execution path
  12. map.isStyleLoaded(): false
  ⏳ Style NOT loaded - registering 'style.load' event listener

🔔 [NDVI STYLE LOAD] Registering map.once('style.load', callback)
  ✅ style.load listener registered - waiting for event...

(time passes...)

🟢 [NDVI STYLE LOAD] 'style.load' event fired
  13. map.isStyleLoaded(): true
  ✅ Now executing sync()

🟢 [NDVI SYNC] sync() function starting
  6. map.isStyleLoaded() inside sync: true
  7. map.getSource exists: false

➕ [NDVI ADD SOURCE] Calling map.addSource()
  ✅ map.addSource() completed without throwing

➕ [NDVI ADD LAYER] Layer does not exist - will create
  ✅ map.addLayer() completed without throwing
  
✅ sync() completed successfully
```
