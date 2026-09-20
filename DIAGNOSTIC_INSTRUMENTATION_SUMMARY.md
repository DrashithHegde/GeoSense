# NDVI Diagnostic Instrumentation Summary

## Changes Made

Added comprehensive diagnostic logging to `client/src/hooks/index.js` in the NDVI useEffect (Line ~191-365).

**NO behavior changes. NO control flow changes. ONLY logging added.**

---

## Instrumentation Added

### 1. [NDVI EFFECT] - useEffect Entry
**Location:** Start of NDVI useEffect

**Logs:**
- When the useEffect fires (timestamp)
- Whether `ndviSurface` parameter exists
- `ndviSurface.image_url` and coordinates if present
- Whether `map` exists
- Value of `map.isStyleLoaded()`
- Whether early return will occur
- Reason for early return (no map / style not loaded / no data)

**Purpose:** Determine if useEffect fires when data arrives and why it might exit early.

---

### 2. [NDVI SYNC] - sync() Function Execution
**Location:** Inside the `sync()` function

**Logs:**
- When sync() starts executing (timestamp)
- Value of `map.isStyleLoaded()` inside sync
- Whether source already exists via `map.getSource(NDVI_SURFACE_SOURCE)`
- Whether updating existing source or creating new one

**Purpose:** Confirm sync() actually executes and determine initial source state.

---

### 3. [NDVI UPDATE SOURCE] - Existing Source Update
**Location:** Inside sync() when source exists

**Logs:**
- That `source.updateImage()` is being called
- The imageOptions being passed

**Purpose:** Track updates to existing source (not expected on first load).

---

### 4. [NDVI ADD SOURCE] - New Source Creation
**Location:** Inside sync() when source doesn't exist

**Logs:**
- That `map.addSource()` is being called
- Source ID: `NDVI_SURFACE_SOURCE`
- Source type: `"image"`
- The imageOptions (URL and coordinates)
- Whether addSource completes without throwing
- Verification: whether source exists after addSource

**Error Handling:**
- Catches any exception from `map.addSource()`
- Logs error message, stack, and full error object
- Exits sync() early on error

**Purpose:** Track source creation attempt and catch any failures.

---

### 5. [NDVI ADD LAYER] - Layer Creation
**Location:** Inside sync() after source is created/updated

**Logs:**
- Whether layer already exists via `map.getLayer(NDVI_SURFACE_LAYER)`
- That layer creation is being attempted
- Layer ID, type, source
- The `beforeId` insertion point (MUNI_EXTRUDE or undefined)
- Whether MUNI_EXTRUDE layer exists
- Whether addLayer completes without throwing
- Verification: whether layer exists after addLayer

**Error Handling:**
- Catches any exception from `map.addLayer()`
- Logs error message, stack, and full error object
- Exits sync() early on error

**Purpose:** Track layer creation attempt and catch any failures.

---

### 6. [NDVI EFFECT] - Sync Execution Decision
**Location:** After sync() function definition, before execution

**Logs:**
- Value of `map.isStyleLoaded()` at decision point
- Whether taking immediate sync path or idle wait path

**Purpose:** Determine which execution path is taken.

---

### 7. [NDVI IDLE] - Idle Event Listener
**Location:** If style not loaded, registers idle listener

**Logs:**
- That idle listener is being registered
- Confirmation that registration succeeded
- When idle event fires (timestamp)
- Value of `map.isStyleLoaded()` when idle fires
- That sync() is executing in response to idle

**Purpose:** Track whether idle event ever fires and when.

---

### 8. [MAPBOX ERROR] - NDVI-Related Errors
**Location:** Enhanced existing Mapbox error listener

**Logs:**
- Special detection for NDVI-related errors (checks sourceId, message, URL)
- Timestamp, error count
- sourceId, error message, error URL
- Full error object and event
- Always logs NDVI errors (bypasses "first 5 errors" limit)
- Flags NDVI errors with `[NDVI]` tag
- Detects `/surface-assets/` or `ndvi` in URLs

**Purpose:** Catch any Mapbox errors specifically related to NDVI source/layer.

---

### 9. [NDVI DATA EVENT] - Data Load Success
**Location:** Enhanced existing `map.on("data")` listener

**Logs:**
- When NDVI source data loads successfully
- Timestamp, sourceId, isSourceLoaded, dataType

**Purpose:** Confirm successful data loading.

---

### 10. [NDVI SOURCEDATA EVENT] - Source Data Events
**Location:** Enhanced existing `map.on("sourcedata")` listener

**Logs:**
- All sourcedata events for NDVI source
- Timestamp, isSourceLoaded, dataType, tile, coord

**Purpose:** Track all source data lifecycle events.

---

## Expected Console Output

### Success Path:
```
🔵 [NDVI EFFECT] useEffect fired
  1. ndviSurface exists: true
  2. map exists: true
  3. ndviSurface exists: true
  4. map.isStyleLoaded(): true
  5. Will early return? false
  ✅ All pre-conditions passed

🔵 [NDVI EFFECT] Deciding sync execution path
  12. map.isStyleLoaded(): true
  ✅ Style is loaded - calling sync() immediately

🟢 [NDVI SYNC] sync() function starting
  6. map.isStyleLoaded() inside sync: true
  7. map.getSource(NDVI_SURFACE_SOURCE) exists: false
  ℹ️ Source does not exist - will create new source

➕ [NDVI ADD SOURCE] Calling map.addSource()
  Source ID: ndvi-surface-source
  ✅ map.addSource() completed without throwing
  8. Verification - source exists: true

➕ [NDVI ADD LAYER] Layer does not exist - will create
  Layer ID: ndvi-surface-layer
  beforeId: muni-extrude
  ✅ map.addLayer() completed without throwing
  10. Verification - layer exists: true

  11. Calling applyMunicipalityPaint with hasNdviSurface=true
  ✅ sync() completed successfully

📡 [NDVI SOURCEDATA EVENT]
  isSourceLoaded: true
  dataType: metadata

✅ [NDVI DATA EVENT] NDVI source data loaded successfully
```

### Blocked by Style Loading:
```
🔵 [NDVI EFFECT] useEffect fired
  1. ndviSurface exists: true
  2. map exists: true
  3. ndviSurface exists: true
  4. map.isStyleLoaded(): false  ← BLOCKED HERE
  5. Will early return? true
  ❌ Early return: map.isStyleLoaded() === false

(no sync() execution)
(no source/layer creation)
```

### Wait for Idle Path:
```
🔵 [NDVI EFFECT] useEffect fired
  ... (all checks pass)

🔵 [NDVI EFFECT] Deciding sync execution path
  12. map.isStyleLoaded(): false  ← NOT READY
  ⏳ Style NOT loaded - registering 'idle' event listener

🔔 [NDVI IDLE] Registering map.once('idle', callback)
  ✅ Idle listener registered - waiting for event...

(time passes...)

🟡 [NDVI IDLE] 'idle' event fired
  13. map.isStyleLoaded() when idle fires: true
  ✅ Now executing sync()

🟢 [NDVI SYNC] sync() function starting
  ... (continues as success path)
```

### Error During Source Creation:
```
🔵 [NDVI EFFECT] useEffect fired
  ... (all checks pass, sync() called)

🟢 [NDVI SYNC] sync() function starting
  7. map.getSource exists: false

➕ [NDVI ADD SOURCE] Calling map.addSource()
  ❌ map.addSource() threw an error
     Error message: [actual error]
     Error stack: [stack trace]

(sync() exits early)
(layer never created)
```

---

## What This Will Tell Us

### If we see:
- **No `[NDVI EFFECT]` logs** → useEffect never fires (React issue)
- **Early return due to no map** → Map not initialized when data arrives
- **Early return due to style not loaded** → Style loading is the blocker
- **Idle listener registered but never fires** → Map never becomes idle (continuous errors)
- **sync() starts but addSource throws** → Mapbox API error
- **Source created but addLayer throws** → Layer creation issue
- **`[MAPBOX ERROR] NDVI-RELATED`** → Specific NDVI resource error

---

## Files Modified

- `client/src/hooks/index.js` - NDVI useEffect section (~Line 191-365)

## Unchanged

- ✅ No behavior changes
- ✅ No control flow changes
- ✅ Dependencies unchanged: `[ndviSurface]`
- ✅ setupLayers() unchanged
- ✅ Layer ordering unchanged
- ✅ Backend/API/PNG unchanged
- ✅ Other useEffects unchanged
